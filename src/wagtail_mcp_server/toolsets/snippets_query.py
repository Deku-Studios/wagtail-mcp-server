"""Read-only snippets query toolset.

New in v0.5. Implements:

    snippets.types   List every registered snippet model (name, label,
                     fields).
    snippets.list    Paginated list of instances of a given snippet type.
    snippets.get     One instance, by type + id.

Wagtail snippets are arbitrary Django models registered via
``@register_snippet``. The canonical enumeration helper is
:func:`wagtail.snippets.models.get_snippet_models`, which this toolset
uses at dispatch time (so snippets registered after startup are
picked up on the next call).

Scope
-----
Reads only. No per-snippet mutation surface in v0.5. Writes will land in
a later release once a `snippets_write` toolset is scoped out.

Per the v0.5 spec, snippet **custom URLs** are explicitly out of scope
(snippets are rarely URL-addressable in practice, and modelling that in
a generic tool would expand the surface area without buying much). The
response shape is deliberately slim -- id, string representation, and
the model's declared ``api_fields``.

Auth
----
Anonymous callers are rejected. Authenticated callers must additionally
hold Django's ``view_<model>`` permission OR be ``is_staff``; otherwise
per-snippet-type dispatch returns a ``PermissionDenied`` that names the
type (no silent empty list, which would be indistinguishable from an
actually empty table).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from mcp_server.djangomcp import MCPToolset

from ..settings import get_config

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100


class SnippetsQueryToolset(MCPToolset):
    """django-mcp-server toolset for read-only Snippet access."""

    name = "snippets_query"
    version = "0.5.0"

    # ------------------------------------------------------------ snippets.types

    def snippets_types(self) -> list[dict[str, Any]]:
        """Return ``[{name, label, fields}, ...]`` for every registered snippet type.

        Does not filter by user permission -- knowing which snippet
        *types* exist is not itself sensitive. Querying instances of a
        type still requires the standard view permission.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        out: list[dict[str, Any]] = []
        for model in _all_snippet_models():
            out.append(
                {
                    "name": _model_identifier(model),
                    "label": str(model._meta.verbose_name),
                    "fields": _api_field_names(model) or _plain_field_names(model),
                }
            )
        return out

    # ------------------------------------------------------------- snippets.list

    def snippets_list(
        self,
        *,
        type: str,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """Paginated list of snippet instances for ``type`` (``"app_label.ModelName"``)."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        model = _resolve_snippet_model(type)
        if model is None:
            raise ValueError(f"Unknown snippet type: {type!r}.")
        _require_view_perm(user, model)

        qs = model._default_manager.all().order_by("pk")
        return _paginate(qs, page, page_size, serializer=_serialize_snippet)

    # -------------------------------------------------------------- snippets.get

    def snippets_get(self, *, type: str, id: int) -> dict[str, Any] | None:
        """Fetch one snippet instance. Returns ``None`` if the id is unknown."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        model = _resolve_snippet_model(type)
        if model is None:
            raise ValueError(f"Unknown snippet type: {type!r}.")
        _require_view_perm(user, model)

        try:
            instance = model._default_manager.get(pk=id)
        except model.DoesNotExist:
            return None
        return _serialize_snippet(instance, include_fields=True)


# ==================================================================== helpers


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Anonymous users cannot call snippets.* tools.")


def _require_view_perm(user: Any, model: Any) -> None:
    """Allow superuser / staff outright; otherwise require ``view_<model>``.

    Wagtail snippets rely on Django's model-level ``view_<model>`` perm
    for admin visibility; mirroring that keeps this toolset consistent
    with what an operator sees in the admin UI.
    """
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return
    codename = f"view_{model._meta.model_name}"
    if not user.has_perm(f"{model._meta.app_label}.{codename}"):
        raise PermissionDenied(
            f"User lacks view permission for snippet type "
            f"{_model_identifier(model)!r}."
        )


def _all_snippet_models() -> list[Any]:
    """Return every registered snippet model, empty list if snippets not installed."""
    try:
        from wagtail.snippets.models import get_snippet_models
    except ImportError:
        return []
    return list(get_snippet_models() or [])


def _resolve_snippet_model(type_name: str) -> Any | None:
    """Resolve ``"app_label.ModelName"`` to a registered snippet model."""
    try:
        app_label, model_name = type_name.split(".", 1)
    except ValueError:
        return None
    lower = model_name.lower()
    for model in _all_snippet_models():
        meta = model._meta
        if meta.app_label == app_label and meta.model_name == lower:
            return model
    return None


def _model_identifier(model: Any) -> str:
    return f"{model._meta.app_label}.{model.__name__}"


def _api_field_names(model: Any) -> list[str]:
    """Return the model's declared ``api_fields``, or empty list."""
    api_fields = getattr(model, "api_fields", None) or []
    out: list[str] = []
    for entry in api_fields:
        if isinstance(entry, str):
            out.append(entry)
        else:
            name = getattr(entry, "name", None)
            if name:
                out.append(name)
    return out


def _plain_field_names(model: Any) -> list[str]:
    """Fallback field enumeration for snippets that don't declare api_fields."""
    return [
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False) and not f.many_to_many
    ]


def _serialize_snippet(instance: Any, *, include_fields: bool = False) -> dict[str, Any]:
    """Slim payload for a snippet instance."""
    payload: dict[str, Any] = {
        "id": instance.pk,
        "type": _model_identifier(instance.__class__),
        "str": str(instance),
    }
    if include_fields:
        payload["fields"] = _dump_concrete_fields(instance)
    return payload


def _dump_concrete_fields(instance: Any) -> dict[str, Any]:
    """Dump concrete (non-relational, non-m2m) field values to a plain dict.

    We deliberately keep this minimal: foreign keys surface as the
    integer pk under ``<field>_id`` (Django's built-in convention), and
    many-to-many relations are skipped. Agents that need deep object
    graphs can follow up with a targeted ``snippets.get`` on the related
    type.
    """
    out: dict[str, Any] = {}
    for field in instance._meta.get_fields():
        if not getattr(field, "concrete", False) or field.many_to_many:
            continue
        attname = getattr(field, "attname", field.name)
        try:
            out[attname] = getattr(instance, attname)
        except AttributeError:
            continue
    return out


def _paginate(
    qs: Any, page: int, page_size: int | None, *, serializer: Any
) -> dict[str, Any]:
    cfg = get_config()
    default_page_size = int(cfg["LIMITS"].get("MAX_PAGE_SIZE", DEFAULT_LIST_LIMIT))
    size = int(page_size or default_page_size)
    if size <= 0:
        raise ValueError("page_size must be positive.")
    if page <= 0:
        raise ValueError("page must be positive.")
    size = min(size, MAX_LIST_LIMIT)
    offset = (page - 1) * size
    total = qs.count()
    rows = list(qs[offset : offset + size])
    return {
        "total": total,
        "page": page,
        "page_size": size,
        "results": [serializer(row) for row in rows],
    }
