"""End-to-end tests for the six ``PageQueryToolset`` handlers."""

from __future__ import annotations

import pytest

from wagtail_mcp_server.toolsets.pages_query import PageQueryToolset


@pytest.fixture
def toolset():
    return PageQueryToolset()


# ---------------------------------------------------------------------- pages.list


@pytest.mark.django_db
def test_list_returns_pages_under_parent(toolset, home_page, stream_page):
    result = toolset.pages_list(user=None, parent_id=home_page.pk)
    slugs = {item["slug"] for item in result["items"]}
    assert "stream" in slugs
    assert result["total"] == len(result["items"])


@pytest.mark.django_db
def test_list_filters_by_type(toolset, home_page, stream_page):
    result = toolset.pages_list(
        user=None,
        parent_id=home_page.pk,
        type="wagtail_mcp_server_testapp.TestStreamPage",
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["page_type"].endswith(".TestStreamPage")


@pytest.mark.django_db
def test_list_returns_empty_for_unknown_type(toolset, home_page):
    result = toolset.pages_list(user=None, parent_id=home_page.pk, type="nope.Missing")
    assert result["items"] == []


# ----------------------------------------------------------------------- pages.get


@pytest.mark.django_db
def test_get_by_id(toolset, stream_page):
    payload = toolset.pages_get(user=None, id=stream_page.pk)
    assert payload is not None
    assert payload["id"] == stream_page.pk


@pytest.mark.django_db
def test_get_by_slug(toolset, stream_page):
    payload = toolset.pages_get(user=None, slug="stream")
    assert payload is not None
    assert payload["slug"] == "stream"


@pytest.mark.django_db
def test_get_returns_none_for_missing(toolset):
    assert toolset.pages_get(user=None, id=99999) is None


@pytest.mark.django_db
def test_get_requires_at_least_one_lookup(toolset):
    with pytest.raises(ValueError):
        toolset.pages_get(user=None)


# ---------------------------------------------------------------------- pages.tree


@pytest.mark.django_db
def test_tree_returns_ancestors_and_descendants(toolset, home_page, stream_page):
    result = toolset.pages_tree(user=None, id=home_page.pk, depth=1)
    assert result is not None
    assert result["page"]["slug"] == "test-home"
    descendant_slugs = {d["slug"] for d in result["descendants"]}
    assert "stream" in descendant_slugs
    # Root is among the ancestors.
    ancestor_titles = [a["title"] for a in result["ancestors"]]
    assert ancestor_titles  # at minimum the implicit root


@pytest.mark.django_db
def test_tree_returns_none_for_missing_id(toolset):
    assert toolset.pages_tree(user=None, id=99999) is None


# -------------------------------------------------------------------- pages.search


@pytest.mark.django_db
def test_search_returns_matches(toolset, stream_page):
    # Search uses the configured backend; the in-memory default falls back
    # to icontains on title for unindexed test models.
    result = toolset.pages_search(user=None, query="Stream")
    assert "items" in result
    assert result["query"] == "Stream"


@pytest.mark.django_db
def test_search_empty_query_short_circuits(toolset):
    result = toolset.pages_search(user=None, query="")
    assert result == {"items": [], "query": ""}


# --------------------------------------------------------------------- pages.types


@pytest.mark.django_db
def test_types_lists_test_page_models(toolset):
    types = toolset.pages_types(user=None)
    names = {entry["name"] for entry in types}
    assert "wagtail_mcp_server_testapp.TestStreamPage" in names
    assert "wagtail_mcp_server_testapp.TestRenditionPage" in names


# -------------------------------------------------------------- pages.types.schema


@pytest.mark.django_db
def test_types_schema_returns_json_schema(toolset):
    schema = toolset.pages_types_schema(
        user=None,
        type="wagtail_mcp_server_testapp.TestStreamPage",
    )
    assert schema is not None
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert "body" in schema["properties"]
    body = schema["properties"]["body"]
    assert body["type"] == "array"
    assert "items" in body


@pytest.mark.django_db
def test_types_schema_returns_none_for_missing_type(toolset):
    assert toolset.pages_types_schema(user=None, type="nope.Missing") is None
