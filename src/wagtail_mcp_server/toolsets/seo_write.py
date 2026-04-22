"""SEO write toolset.

Off by default. Narrow sibling of :class:`PageWriteToolset` that only
touches SEO fields:

    seo.update   Update seo_title, search_description, slug, og_image.

After the write the toolset re-runs :attr:`SEOQueryToolset.RULES` on the
updated page and returns the post-write findings. This means an agent
that fixes a short description gets told immediately if it's still out
of the recommended range, without a round-trip to ``seo.audit``.

Why a separate toolset and not a flag on ``pages.update``?

    - Different permission surface. Letting an agent tune SEO copy is a
      lower-trust operation than letting it restructure a StreamField
      body; hosts may want to enable one and not the other.
    - Stable field list. ``seo.update`` advertises exactly four fields.
      Unknown fields are rejected (not silently dropped as in
      ``pages.update``) so agent errors surface early.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from mcp_server.djangomcp import MCPToolset

from .pages_write import (
    _can_edit,
    _can_publish,
    _page_write_result,
    _require_authenticated,
    _resolve_fk,
)
from .seo_query import _audit_page

# Canonical set of fields seo.update is allowed to mutate. The lex-admin
# UI, the JSON schema generator, and the agent-facing prompt all read
# from this constant -- do not fork.
SEO_FIELDS: tuple[str, ...] = (
    "seo_title",
    "search_description",
    "slug",
    "og_image",
)


class SEOWriteToolset(MCPToolset):
    """django-mcp-server toolset for mutating SEO fields on a page.

    The caller is resolved from ``self.request.user`` (populated by
    :class:`wagtail_mcp_server.auth.UserTokenDRFAuth` on HTTP, or by the
    stdio bootstrap on local runs). Every tool method is published as an
    MCP tool by ``ToolsetMeta``; helper methods are underscore-prefixed
    so they stay off the wire.
    """

    name = "seo_write"
    version = "0.4.0"

    # ------------------------------------------------------------------ seo.update

    def seo_update(
        self,
        *,
        id: int,
        fields: dict[str, Any],
        publish: bool = False,
    ) -> dict[str, Any]:
        """Update one or more SEO fields on the page.

        Any key in ``fields`` that is not in :data:`SEO_FIELDS` raises
        ``ValueError`` -- this is stricter than ``pages.update`` (which
        drops unknown keys) because the whole point of this tool is to
        advertise a small, stable surface.

        ``og_image`` accepts the same forms as any other ``ChooserBlock``
        target: an ``int`` pk, ``{"_raw_id": int}``, or an already-resolved
        Image instance.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        if not fields:
            raise ValueError("seo.update requires a non-empty fields dict.")
        unknown = set(fields.keys()) - set(SEO_FIELDS)
        if unknown:
            raise ValueError(
                "seo.update does not accept these fields: "
                f"{sorted(unknown)}. Allowed: {list(SEO_FIELDS)}."
            )

        page = _get_page_or_404(id).specific
        if not _can_edit(user, page):
            raise PermissionDenied(f"User lacks edit permission for page {id}.")

        model = type(page)
        prepared = _prepare_seo_fields(model, fields)
        for name, value in prepared.items():
            setattr(page, name, value)

        revision = page.save_revision(user=user)
        result = _page_write_result(page, revision)

        if publish:
            if not _can_publish(user, page):
                raise PermissionDenied(
                    f"User lacks publish permission for page {page.pk}."
                )
            revision.publish(user=user)
            page.refresh_from_db()
            result["live"] = bool(page.live)

        # Post-write audit -- let the agent see whether its fix landed in
        # the recommended range, or whether more work is needed.
        result["findings"] = _audit_page(page)
        return result


# --------------------------------------------------------------------- helpers


def _get_page_or_404(page_id: int) -> Any:
    from wagtail.models import Page

    try:
        return Page.objects.get(pk=page_id)
    except Page.DoesNotExist as exc:
        raise ValueError(f"Page id={page_id} does not exist.") from exc


def _prepare_seo_fields(model: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce SEO-field inputs into Wagtail-native values.

    - ``seo_title``, ``search_description``, ``slug`` pass through as
      strings. None coerces to empty string for consistency with Wagtail.
    - ``og_image`` is optional on the model (not every Page subclass
      adds it). If the model has it, the value is resolved against the
      related Image model; if it doesn't, supplying ``og_image`` raises.
    """
    from django.core.exceptions import FieldDoesNotExist
    from django.db import models as dj_models

    out: dict[str, Any] = {}
    for name, value in fields.items():
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist as exc:
            raise ValueError(
                f"Page model {model.__name__} has no field '{name}'. "
                f"seo.update accepts {list(SEO_FIELDS)} only when the "
                f"target model declares them."
            ) from exc

        if isinstance(field, dj_models.ForeignKey):
            out[name] = _resolve_fk(field, value)
        else:
            out[name] = "" if value is None else value
    return out
