"""End-to-end tests for the ``SnippetsQueryToolset`` handlers.

The testapp registers a minimal ``TestAuthor`` snippet model, so
``snippets.types`` always has at least one entry to enumerate and the
list + get flows have a concrete model to operate on.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.toolsets.snippets_query import SnippetsQueryToolset


@pytest.fixture
def toolset():
    return SnippetsQueryToolset()


@pytest.fixture
def authors(db):
    """Create a few ``TestAuthor`` snippet instances."""
    from tests.testapp.models import TestAuthor

    a = TestAuthor.objects.create(name="Alex")
    b = TestAuthor.objects.create(name="Blair")
    c = TestAuthor.objects.create(name="Chris")
    return [a, b, c]


SNIPPET_TYPE = "wagtail_mcp_server_testapp.TestAuthor"


# ------------------------------------------------------------- auth gating


@pytest.mark.django_db
def test_types_rejects_anonymous(toolset, bind_user):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).snippets_types()


@pytest.mark.django_db
def test_list_rejects_anonymous(toolset, bind_user):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).snippets_list(type=SNIPPET_TYPE)


# -------------------------------------------------------- snippets.types


@pytest.mark.django_db
def test_types_enumerates_registered_snippets(toolset, bind_user, staff_user):
    types = bind_user(toolset, staff_user).snippets_types()
    names = {row["name"] for row in types}
    assert SNIPPET_TYPE in names
    entry = next(row for row in types if row["name"] == SNIPPET_TYPE)
    # Fields should at minimum surface the custom CharField.
    assert "name" in entry["fields"]


# --------------------------------------------------------- snippets.list


@pytest.mark.django_db
def test_list_returns_instances(toolset, bind_user, staff_user, authors):
    result = bind_user(toolset, staff_user).snippets_list(type=SNIPPET_TYPE)
    assert result["total"] == len(authors)
    names = {row["str"] for row in result["results"]}
    assert names == {"Alex", "Blair", "Chris"}


@pytest.mark.django_db
def test_list_unknown_type_raises(toolset, bind_user, staff_user):
    with pytest.raises(ValueError, match="Unknown snippet type"):
        bind_user(toolset, staff_user).snippets_list(type="nope.Missing")


# ---------------------------------------------------------- snippets.get


@pytest.mark.django_db
def test_get_returns_fields(toolset, bind_user, staff_user, authors):
    target = authors[1]
    payload = bind_user(toolset, staff_user).snippets_get(
        type=SNIPPET_TYPE, id=target.pk
    )
    assert payload is not None
    assert payload["id"] == target.pk
    assert payload["str"] == "Blair"
    assert payload["fields"]["name"] == "Blair"


@pytest.mark.django_db
def test_get_returns_none_for_missing_id(toolset, bind_user, staff_user):
    assert (
        bind_user(toolset, staff_user).snippets_get(type=SNIPPET_TYPE, id=999999)
        is None
    )
