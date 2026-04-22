"""Read-only page query toolset.

Implements in v0.1:

    pages.list           Paginated list of live pages, optionally filtered.
    pages.get            Full page payload with StreamField envelope.
    pages.tree           Ancestors + children of a given page.
    pages.search         Full-text search delegated to Wagtail search.
    pages.types          Names of registered ``Page`` subclasses.
    pages.types.schema   JSON schema for a specific page type.

All tools are side-effect free and safe to expose by default. Each tool
is scoped to pages the authenticated user has ``view_page`` on; Wagtail
permissions apply.

v0.1 ships pure-Python handlers without the django-mcp-server ``@tool``
decorator so the toolset is testable in isolation. The decorator wrap
lands in v0.2 alongside the rest of the transport wiring.
"""

from __future__ import annotations

from typing import Any

from ..schema import build_page_type_schema
from ..serializers.page import PageSerializer
from ..serializers.page_ref import serialize_page_ref
from ..serializers.streamfield import SerializeOptions

# Pagination defaults chosen to balance "useful first response" against
# "do not blow the agent's context window". Hosts override via the
# ``LIMITS`` config dict.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
DEFAULT_SEARCH_LIMIT = 25


class PageQueryToolset:
    """django-mcp-server toolset for read-only page access.

    The toolset takes options up front so the handlers do not have to
    re-parse settings on every call. ``options`` controls richtext format,
    chooser preview inclusion, and any future read-time knobs.
    """

    name = "pages_query"
    version = "0.1.0"

    def __init__(self, *, options: SerializeOptions | None = None) -> None:
        self.options = options or SerializeOptions()
        self.serializer = PageSerializer(options=self.options)

    # ------------------------------------------------------------------ pages.list

    def pages_list(
        self,
        user: Any,
        *,
        parent_id: int | None = None,
        type: str | None = None,
        live: bool = True,
        slug: str | None = None,
        locale: str | None = None,
        search: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List pages under ``parent_id`` (or site root) with filters applied."""
        qs = self._scoped_queryset(user)
        if parent_id is not None:
            parent = self._get_page_or_none(parent_id)
            if parent is None:
                return _empty_page_list()
            qs = qs.child_of(parent)
        if live:
            qs = qs.live()
        if slug:
            qs = qs.filter(slug=slug)
        if locale:
            qs = qs.filter(locale__language_code=locale)
        if type:
            model = _resolve_page_model(type)
            if model is None:
                return _empty_page_list()
            qs = qs.type(model)
        if search:
            # ``search`` here delegates to the configured Wagtail search
            # backend; for the in-memory test backend it falls back to
            # icontains on title.
            qs = qs.search(search).get_queryset()

        limit = max(0, min(int(limit), MAX_LIST_LIMIT))
        total = qs.count()
        rows = list(qs.order_by("path")[offset : offset + limit])

        return {
            "items": [serialize_page_ref(p.specific) for p in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    # ------------------------------------------------------------------- pages.get

    def pages_get(
        self,
        user: Any,
        *,
        id: int | None = None,
        slug: str | None = None,
        url_path: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one page by id, slug, or url_path."""
        if id is None and slug is None and url_path is None:
            raise ValueError("pages.get requires one of: id, slug, url_path")

        qs = self._scoped_queryset(user)
        if id is not None:
            qs = qs.filter(pk=id)
        if slug is not None:
            qs = qs.filter(slug=slug)
        if url_path is not None:
            qs = qs.filter(url_path=url_path)
        page = qs.first()
        if page is None:
            return None
        return self.serializer.serialize(page.specific)

    # ------------------------------------------------------------------ pages.tree

    def pages_tree(
        self,
        user: Any,
        *,
        id: int,
        depth: int = 1,
    ) -> dict[str, Any] | None:
        """Return ancestors + immediate descendants for ``id``.

        ``depth`` applies to the descendants only. Ancestors always go all
        the way to the root because they are cheap and orient the agent.
        """
        page = self._get_page_or_none(id)
        if page is None or not _user_can_view(user, page):
            return None

        ancestors = page.get_ancestors()
        descendants = page.get_descendants().filter(depth__lte=page.depth + max(0, int(depth)))
        scoped = self._scoped_queryset(user)
        descendants = descendants.filter(pk__in=scoped.values_list("pk", flat=True))

        return {
            "page": serialize_page_ref(page.specific),
            "ancestors": [serialize_page_ref(a.specific) for a in ancestors],
            "descendants": [serialize_page_ref(d.specific) for d in descendants.order_by("path")],
        }

    # ---------------------------------------------------------------- pages.search

    def pages_search(
        self,
        user: Any,
        *,
        query: str,
        type: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> dict[str, Any]:
        """Full-text search against Wagtail's configured search backend."""
        if not query:
            return {"items": [], "query": query}

        qs = self._scoped_queryset(user).live()
        if type:
            model = _resolve_page_model(type)
            if model is None:
                return {"items": [], "query": query}
            qs = qs.type(model)

        limit = max(0, min(int(limit), MAX_LIST_LIMIT))
        results = qs.search(query)[:limit]

        return {
            "items": [serialize_page_ref(p.specific) for p in results],
            "query": query,
        }

    # ----------------------------------------------------------------- pages.types

    def pages_types(self, user: Any) -> list[dict[str, Any]]:
        """Return ``[{name, label, fields}, ...]`` for every registered page type."""
        from wagtail.models import get_page_models

        out: list[dict[str, Any]] = []
        for model in get_page_models():
            out.append(
                {
                    "name": f"{model._meta.app_label}.{model.__name__}",
                    "label": str(model._meta.verbose_name),
                    "fields": _api_field_names(model),
                }
            )
        return out

    # ------------------------------------------------------------ pages.types.schema

    def pages_types_schema(self, user: Any, *, type: str) -> dict[str, Any] | None:
        """JSON Schema for the given page type's writable shape."""
        model = _resolve_page_model(type)
        if model is None:
            return None
        return build_page_type_schema(model)

    # ---------------------------------------------------------------- internal

    def _scoped_queryset(self, user: Any) -> Any:
        """Return a queryset of pages this user is allowed to view.

        Combines Wagtail's own ``get_pages_for_user`` (permission-aware)
        with the standard ``live()`` filter for the public reads path.
        Anonymous users get the same set ``Site`` resolution gives them.
        """
        from wagtail.models import Page

        qs = Page.objects.all()
        if user is None or not getattr(user, "is_authenticated", False):
            return qs.live()
        # Wagtail >=2.16 attaches the helper to user via the page-permission
        # mixin; we duck-check first so unit tests with a bare User pass.
        per_user_qs = getattr(user, "get_pages_for_user", None)
        if callable(per_user_qs):
            return qs & per_user_qs()  # type: ignore[operator]
        return qs

    def _get_page_or_none(self, page_id: int) -> Any | None:
        from wagtail.models import Page

        try:
            return Page.objects.get(pk=page_id)
        except Page.DoesNotExist:
            return None


# --------------------------------------------------------------------------- helpers


def _empty_page_list() -> dict[str, Any]:
    return {"items": [], "total": 0, "offset": 0, "limit": 0}


def _resolve_page_model(type_name: str) -> Any | None:
    """Resolve ``"app_label.ClassName"`` to a Page subclass, or ``None``."""
    from django.apps import apps

    try:
        app_label, model_name = type_name.split(".", 1)
    except ValueError:
        return None
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _user_can_view(user: Any, page: Any) -> bool:
    """Best-effort permission check for ``view_page`` on ``page``."""
    if user is None or not getattr(user, "is_authenticated", False):
        return page.live
    perms_for_page = getattr(page, "permissions_for_user", None)
    if callable(perms_for_page):
        try:
            return perms_for_page(user).can_view()
        except Exception:  # noqa: BLE001 -- fall back to live filter
            return page.live
    return page.live


def _api_field_names(model: Any) -> list[str]:
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
