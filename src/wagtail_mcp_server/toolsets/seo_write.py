"""SEO write toolset.

Off by default. Narrow sibling of :class:`PageWriteToolset` that only
touches SEO fields:

    seo.update              Update seo_title, search_description, slug, og_image.
    seo.sitemap.regenerate  (v0.5) Recount the live sitemap, bust host caches.

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

``seo.sitemap.regenerate`` caveat
---------------------------------
The library does not assume a caching strategy -- Wagtail's
``wagtail.contrib.sitemaps`` view is uncached out of the box, but most
production deployments wrap it in :func:`django.views.decorators.cache.cache_page`
or a CDN. The tool therefore does two things:

    1. Walks the current live-page set and returns count + timestamp so
       the agent can confirm the sitemap reflects recent changes.
    2. Optionally deletes a caller-supplied list of cache keys via
       :mod:`django.core.cache`, and fires a
       :data:`sitemap_regenerated` signal so hosts can hook in
       (CloudFront invalidation, nginx purge, etc.).
"""

from __future__ import annotations

from typing import Any

import django.dispatch
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

# Fired by ``seo.sitemap.regenerate`` after the count + cache-key delete.
# Hosts subscribe to trigger their own cache invalidation (CDN, nginx,
# reverse proxy). Kwargs: ``user``, ``page_count``, ``cache_keys_busted``.
sitemap_regenerated = django.dispatch.Signal()

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
    version = "0.5.0"

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

    # ----------------------------------------------------- seo.sitemap.regenerate

    def seo_sitemap_regenerate(
        self,
        *,
        cache_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recount the live sitemap, optionally busting caller-specified cache keys.

        New in v0.5. The tool is deliberately permissive on *what* it
        regenerates: it does not write a ``sitemap.xml`` file to disk
        (Wagtail's sitemap view is dynamic), and it makes no assumption
        about which cache backend the host uses. Behaviour:

        1. Walks ``Page.objects.live()`` and returns the count.
        2. If ``cache_keys`` is given, deletes each key from the default
           :mod:`django.core.cache`. Unknown keys are no-ops. The list of
           keys that were passed in comes back as ``cache_keys_busted``.
        3. Fires :data:`sitemap_regenerated` so hosts can hook in
           (CDN invalidation, reverse-proxy purge, etc.).

        The caller must hold ``wagtailadmin.access_admin`` (or be a
        superuser). This is the same delegation Wagtail uses for
        admin-surface reads, and it deliberately does not require a
        page-level permission because sitemap regeneration is a site-wide
        op rather than a per-page one.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_admin_access(user)

        from django.utils import timezone
        from wagtail.models import Page

        page_count = Page.objects.live().count()

        cache_keys_busted: list[str] = []
        if cache_keys:
            from django.core.cache import cache

            for key in cache_keys:
                cache.delete(key)
                cache_keys_busted.append(key)

        generated_at = timezone.now().isoformat()

        sitemap_regenerated.send(
            sender=type(self),
            user=user,
            page_count=page_count,
            cache_keys_busted=tuple(cache_keys_busted),
        )

        return {
            "regenerated": True,
            "page_count": page_count,
            "cache_keys_busted": cache_keys_busted,
            "generated_at": generated_at,
        }


# --------------------------------------------------------------------- helpers


def _require_admin_access(user: Any) -> None:
    """Require ``wagtailadmin.access_admin`` (or superuser)."""
    if getattr(user, "is_superuser", False):
        return
    if not user.has_perm("wagtailadmin.access_admin"):
        raise PermissionDenied(
            "seo.sitemap.regenerate requires the 'wagtailadmin.access_admin' "
            "permission (or superuser)."
        )


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
