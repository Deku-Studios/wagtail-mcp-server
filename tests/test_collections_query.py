"""End-to-end tests for the ``CollectionsQueryToolset`` handlers.

Covers the three v0.5 tools:

    collections.list   authenticated-only, paginated flat view
    collections.get    single node with lineage, ``None`` for missing
    collections.tree   nested tree from root or given subtree root

Wagtail's migrations seed a single root ``Collection`` at depth 1. Tests
add children under that root via treebeard's ``add_child`` API.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.toolsets.collections_query import CollectionsQueryToolset


@pytest.fixture
def toolset():
    return CollectionsQueryToolset()


@pytest.fixture
def collection_tree(db):
    """Create a small collection tree: Root > Marketing > Brand Assets."""
    from wagtail.models import Collection

    root = Collection.get_first_root_node()
    marketing = root.add_child(instance=Collection(name="Marketing"))
    brand = marketing.add_child(instance=Collection(name="Brand Assets"))
    return {"root": root, "marketing": marketing, "brand": brand}


# ---------------------------------------------------------------- auth gating


@pytest.mark.django_db
def test_list_rejects_anonymous(toolset, bind_user, collection_tree):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).collections_list()


@pytest.mark.django_db
def test_get_rejects_anonymous(toolset, bind_user, collection_tree):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).collections_get(id=collection_tree["marketing"].pk)


@pytest.mark.django_db
def test_tree_rejects_anonymous(toolset, bind_user, collection_tree):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).collections_tree()


# -------------------------------------------------------- collections.list


@pytest.mark.django_db
def test_list_returns_every_collection(
    toolset, bind_user, staff_user, collection_tree
):
    result = bind_user(toolset, staff_user).collections_list()
    names = {row["name"] for row in result["results"]}
    # The root's display name varies ("Root") but it should be listed
    # alongside our two children.
    assert "Marketing" in names
    assert "Brand Assets" in names
    assert result["total"] >= 3
    assert result["page"] == 1


@pytest.mark.django_db
def test_list_paginates(toolset, bind_user, staff_user, collection_tree):
    result = bind_user(toolset, staff_user).collections_list(page=1, page_size=2)
    assert result["page_size"] == 2
    assert len(result["results"]) == 2


# --------------------------------------------------------- collections.get


@pytest.mark.django_db
def test_get_returns_node_with_ancestors(
    toolset, bind_user, staff_user, collection_tree
):
    brand = collection_tree["brand"]
    payload = bind_user(toolset, staff_user).collections_get(id=brand.pk)
    assert payload is not None
    assert payload["name"] == "Brand Assets"
    # Brand lives under Marketing under Root, so the ancestor lineage
    # should include both in order.
    ancestor_names = [a["name"] for a in payload["ancestors"]]
    assert "Marketing" in ancestor_names


@pytest.mark.django_db
def test_get_returns_none_for_missing(toolset, bind_user, staff_user):
    assert bind_user(toolset, staff_user).collections_get(id=999999) is None


# -------------------------------------------------------- collections.tree


@pytest.mark.django_db
def test_tree_from_root(toolset, bind_user, staff_user, collection_tree):
    tree = bind_user(toolset, staff_user).collections_tree()
    assert tree is not None
    # The root should be the top node; Marketing should appear as a child
    # with Brand Assets nested underneath it.
    top_children = {c["name"]: c for c in tree["children"]}
    assert "Marketing" in top_children
    marketing = top_children["Marketing"]
    grand_names = {g["name"] for g in marketing["children"]}
    assert "Brand Assets" in grand_names


@pytest.mark.django_db
def test_tree_from_subtree_root(
    toolset, bind_user, staff_user, collection_tree
):
    marketing = collection_tree["marketing"]
    tree = bind_user(toolset, staff_user).collections_tree(id=marketing.pk)
    assert tree is not None
    assert tree["name"] == "Marketing"
    child_names = {c["name"] for c in tree["children"]}
    assert child_names == {"Brand Assets"}


@pytest.mark.django_db
def test_tree_returns_none_for_missing_id(
    toolset, bind_user, staff_user, collection_tree
):
    assert bind_user(toolset, staff_user).collections_tree(id=999999) is None
