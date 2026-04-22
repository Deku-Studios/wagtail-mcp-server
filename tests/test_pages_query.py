"""End-to-end tests for the six ``PageQueryToolset`` handlers.

Toolset instances are bound to a user via ``bind_user`` (see conftest).
``pages.*`` query tools treat an unauthenticated caller as "public"
(live pages only), so most tests here bind ``None``.
"""

from __future__ import annotations

import pytest

from wagtail_mcp_server.toolsets.pages_query import PageQueryToolset


@pytest.fixture
def toolset():
    return PageQueryToolset()


# ---------------------------------------------------------------------- pages.list


@pytest.mark.django_db
def test_list_returns_pages_under_parent(
    toolset, bind_user, home_page, stream_page
):
    result = bind_user(toolset, None).pages_list(parent_id=home_page.pk)
    slugs = {item["slug"] for item in result["items"]}
    assert "stream" in slugs
    assert result["total"] == len(result["items"])


@pytest.mark.django_db
def test_list_filters_by_type(toolset, bind_user, home_page, stream_page):
    result = bind_user(toolset, None).pages_list(
        parent_id=home_page.pk,
        type="wagtail_mcp_server_testapp.TestStreamPage",
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["page_type"].endswith(".TestStreamPage")


@pytest.mark.django_db
def test_list_returns_empty_for_unknown_type(toolset, bind_user, home_page):
    result = bind_user(toolset, None).pages_list(
        parent_id=home_page.pk, type="nope.Missing"
    )
    assert result["items"] == []


# ----------------------------------------------------------------------- pages.get


@pytest.mark.django_db
def test_get_by_id(toolset, bind_user, stream_page):
    payload = bind_user(toolset, None).pages_get(id=stream_page.pk)
    assert payload is not None
    assert payload["id"] == stream_page.pk


@pytest.mark.django_db
def test_get_by_slug(toolset, bind_user, stream_page):
    payload = bind_user(toolset, None).pages_get(slug="stream")
    assert payload is not None
    assert payload["slug"] == "stream"


@pytest.mark.django_db
def test_get_returns_none_for_missing(toolset, bind_user):
    assert bind_user(toolset, None).pages_get(id=99999) is None


@pytest.mark.django_db
def test_get_requires_at_least_one_lookup(toolset, bind_user):
    with pytest.raises(ValueError):
        bind_user(toolset, None).pages_get()


# ---------------------------------------------------------------------- pages.tree


@pytest.mark.django_db
def test_tree_returns_ancestors_and_descendants(
    toolset, bind_user, home_page, stream_page
):
    result = bind_user(toolset, None).pages_tree(id=home_page.pk, depth=1)
    assert result is not None
    assert result["page"]["slug"] == "test-home"
    descendant_slugs = {d["slug"] for d in result["descendants"]}
    assert "stream" in descendant_slugs
    # Root is among the ancestors.
    ancestor_titles = [a["title"] for a in result["ancestors"]]
    assert ancestor_titles  # at minimum the implicit root


@pytest.mark.django_db
def test_tree_returns_none_for_missing_id(toolset, bind_user):
    assert bind_user(toolset, None).pages_tree(id=99999) is None


# -------------------------------------------------------------------- pages.search


@pytest.mark.django_db
def test_search_returns_matches(toolset, bind_user, stream_page):
    # Search uses the configured backend; the in-memory default falls back
    # to icontains on title for unindexed test models.
    result = bind_user(toolset, None).pages_search(query="Stream")
    assert "items" in result
    assert result["query"] == "Stream"


@pytest.mark.django_db
def test_search_empty_query_short_circuits(toolset, bind_user):
    result = bind_user(toolset, None).pages_search(query="")
    assert result == {"items": [], "query": ""}


# --------------------------------------------------------------------- pages.types


@pytest.mark.django_db
def test_types_lists_test_page_models(toolset, bind_user):
    types = bind_user(toolset, None).pages_types()
    names = {entry["name"] for entry in types}
    assert "wagtail_mcp_server_testapp.TestStreamPage" in names
    assert "wagtail_mcp_server_testapp.TestRenditionPage" in names


# -------------------------------------------------------------- pages.types.schema


@pytest.mark.django_db
def test_types_schema_returns_json_schema(toolset, bind_user):
    schema = bind_user(toolset, None).pages_types_schema(
        type="wagtail_mcp_server_testapp.TestStreamPage",
    )
    assert schema is not None
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert "body" in schema["properties"]
    body = schema["properties"]["body"]
    assert body["type"] == "array"
    assert "items" in body


@pytest.mark.django_db
def test_types_schema_returns_none_for_missing_type(toolset, bind_user):
    assert bind_user(toolset, None).pages_types_schema(type="nope.Missing") is None
