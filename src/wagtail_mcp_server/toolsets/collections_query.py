"""Read-only collections query toolset.

New in v0.5. Implements:

    collections.list   Flat, paginated list of collections.
    collections.get    One collection by id, including its lineage.
    collections.tree   Nested tree view rooted at the global root or any
                       given subtree.

Wagtail's :class:`wagtail.models.Collection` is a treebeard ``MP_Node``
tree. Collections themselves are organisational metadata -- the
sensitive surface (images and documents *inside* a collection) is gated
by the media toolset. For that reason, this toolset exposes the *names
and shape* of the tree to any authenticated caller, rather than trying
to scope by per-collection add/change permissions. That mirrors how
Wagtail's own admin chooser surfaces collection names in dropdowns to
users who can't necessarily write into every node.

Anonymous callers are rejected. Collection metadata is internal-by-default.

The toolset follows the same conventions as ``PageQueryToolset``: the
caller is read from ``self.request.user`` on every call, queries are
side-effect free, and the response shape is JSON-serialisable.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from mcp_server.djangomcp import MCPToolset

from ..settings import get_config

# Pagination defaults. Same shape as the rest of the package -- hosts
# override via ``LIMITS.MAX_PAGE_SIZE`` (capped at the same ceiling).
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100


class CollectionsQueryToolset(MCPToolset):
    """django-mcp-server toolset for read-only Collection access."""

    name = "collections_query"
    version = "0.5.0"

    # ------------------------------------------------------------ collections.list

    def collections_list(
        self,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """Flat, paginated list of all collections in tree order."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.models import Collection

        qs = Collection.objects.all().order_by("path")
        return _paginate(qs, page, page_size, serializer=_serialize_collection)

    # ------------------------------------------------------------- collections.get

    def collections_get(self, *, id: int) -> dict[str, Any] | None:
        """Return one collection by id, with its ancestor lineage.

        Returns ``None`` (not an exception) for an unknown id, matching
        ``pages.get``'s convention so the agent can probe without
        triggering an error path.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.models import Collection

        try:
            collection = Collection.objects.get(pk=id)
        except Collection.DoesNotExist:
            return None

        # Ancestors include all parents up to (but excluding) the root by
        # default; treebeard's ``include_self=False`` is the implicit
        # default and matches ``pages.tree``'s shape.
        ancestors = list(collection.get_ancestors())
        return {
            **_serialize_collection(collection),
            "ancestors": [_serialize_collection(a) for a in ancestors],
        }

    # ------------------------------------------------------------ collections.tree

    def collections_tree(self, *, id: int | None = None) -> dict[str, Any] | None:
        """Return a nested tree of collections.

        When ``id`` is omitted, the tree is rooted at the global root.
        When ``id`` is provided, the tree is the subtree under that
        collection (root included). Returns ``None`` if ``id`` is given
        but does not resolve.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.models import Collection

        if id is None:
            root = Collection.get_first_root_node()
            if root is None:
                return None
        else:
            try:
                root = Collection.objects.get(pk=id)
            except Collection.DoesNotExist:
                return None

        # Pull the whole subtree once, then assemble the nested shape in
        # Python rather than walking the DB per node. ``get_descendants``
        # returns nodes in tree order; combined with ``include_self`` we
        # get a single ordered list.
        nodes = [root, *root.get_descendants()]
        return _build_tree(root, nodes)


# ===================================================================== helpers


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied(
            "Anonymous users cannot call collections.* tools."
        )


def _serialize_collection(collection: Any) -> dict[str, Any]:
    """Slim payload for a single collection node."""
    return {
        "id": collection.pk,
        "name": collection.name,
        "path": collection.path,
        "depth": collection.depth,
        "parent_id": (
            collection.get_parent().pk if collection.depth > 1 else None
        ),
    }


def _build_tree(root: Any, nodes: list[Any]) -> dict[str, Any]:
    """Build a nested tree dict from a tree-ordered ``[root, *descendants]``."""
    by_path: dict[str, dict[str, Any]] = {}
    out: dict[str, Any] | None = None
    for node in nodes:
        entry = {**_serialize_collection(node), "children": []}
        by_path[node.path] = entry
        if node.path == root.path:
            out = entry
            continue
        # Treebeard MP_Node paths are concatenated fixed-width slugs;
        # the parent's path is a prefix of length depth-1 * step.
        parent_path = node.path[: -node.steplen]
        parent_entry = by_path.get(parent_path)
        if parent_entry is not None:
            parent_entry["children"].append(entry)
    assert out is not None  # ``root`` is always in ``nodes``
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
