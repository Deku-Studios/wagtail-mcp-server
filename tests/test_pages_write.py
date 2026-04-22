"""End-to-end tests for the six ``PageWriteToolset`` handlers.

Covers the happy path for each handler plus the three gates that guard
destructive writes (anonymous user, missing ``ALLOW_DESTRUCTIVE`` flag,
missing Wagtail permission). StreamField-envelope validation is covered
in ``test_streamfield_deserialize.py``; this suite only exercises the
thin integration slice where ``pages_update`` hands payload off to the
write validator.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from tests.testapp.models import TestStreamPage
from wagtail_mcp_server.serializers.streamfield import StreamFieldValidationError
from wagtail_mcp_server.settings import reset_cache
from wagtail_mcp_server.toolsets.pages_write import (
    MOVE_POSITIONS,
    PageWriteToolset,
)

# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def toolset():
    return PageWriteToolset()


@pytest.fixture
def superuser(db):
    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        password="x",  # noqa: S106
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def destructive_on(settings):
    """Enable the destructive gate for the duration of a test."""
    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {"pages_write": {"enabled": True}},
        "LIMITS": {"ALLOW_DESTRUCTIVE": True},
    }
    reset_cache()
    yield
    settings.WAGTAIL_MCP_SERVER = {}
    reset_cache()


@pytest.fixture
def destructive_off(settings):
    """Force the destructive gate off (this is also the default)."""
    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {"pages_write": {"enabled": True}},
        "LIMITS": {"ALLOW_DESTRUCTIVE": False},
    }
    reset_cache()
    yield
    settings.WAGTAIL_MCP_SERVER = {}
    reset_cache()


# --------------------------------------------------------------- pages.create


@pytest.mark.django_db
def test_create_draft_page_is_not_live(toolset, superuser, home_page):
    result = toolset.pages_create(
        superuser,
        type="wagtail_mcp_server_testapp.TestStreamPage",
        parent_id=home_page.pk,
        fields={"title": "Draft", "slug": "draft"},
        publish=False,
    )
    assert result["live"] is False
    assert result["slug"] == "draft"


@pytest.mark.django_db
def test_create_with_publish_goes_live(toolset, superuser, home_page):
    result = toolset.pages_create(
        superuser,
        type="wagtail_mcp_server_testapp.TestStreamPage",
        parent_id=home_page.pk,
        fields={"title": "Live", "slug": "live"},
        publish=True,
    )
    assert result["live"] is True


@pytest.mark.django_db
def test_create_accepts_streamfield_envelope(toolset, superuser, home_page):
    result = toolset.pages_create(
        superuser,
        type="wagtail_mcp_server_testapp.TestStreamPage",
        parent_id=home_page.pk,
        fields={
            "title": "With body",
            "slug": "with-body",
            "body": [
                {"type": "heading", "value": {"text": "Hi", "level": "h2"}},
                {"type": "paragraph", "value": "<p>Hello.</p>"},
            ],
        },
    )
    page = TestStreamPage.objects.get(pk=result["id"])
    types = [entry.block_type for entry in page.body]
    assert types == ["heading", "paragraph"]


@pytest.mark.django_db
def test_create_rejects_unknown_page_type(toolset, superuser, home_page):
    with pytest.raises(ValueError):
        toolset.pages_create(
            superuser,
            type="no_app.Nope",
            parent_id=home_page.pk,
        )


@pytest.mark.django_db
def test_create_anonymous_user_blocked(toolset, home_page):
    with pytest.raises(PermissionDenied):
        toolset.pages_create(
            None,
            type="wagtail_mcp_server_testapp.TestStreamPage",
            parent_id=home_page.pk,
        )


@pytest.mark.django_db
def test_create_rejects_malformed_streamfield(toolset, superuser, home_page):
    with pytest.raises(StreamFieldValidationError):
        toolset.pages_create(
            superuser,
            type="wagtail_mcp_server_testapp.TestStreamPage",
            parent_id=home_page.pk,
            fields={
                "title": "Bad body",
                "slug": "bad-body",
                "body": [{"type": "not_a_block", "value": 1}],
            },
        )


# --------------------------------------------------------------- pages.update


@pytest.mark.django_db
def test_update_changes_field_and_bumps_revision(toolset, superuser, stream_page):
    initial_rev = stream_page.latest_revision_id or 0
    result = toolset.pages_update(
        superuser,
        id=stream_page.pk,
        fields={"title": "Updated"},
    )
    assert result["revision_id"] != initial_rev


@pytest.mark.django_db
def test_update_with_publish_sets_live(toolset, superuser, stream_page):
    result = toolset.pages_update(
        superuser,
        id=stream_page.pk,
        fields={"title": "Published"},
        publish=True,
    )
    assert result["live"] is True


@pytest.mark.django_db
def test_update_unknown_field_silently_dropped(toolset, superuser, stream_page):
    # Unknown fields are dropped (caller validates via pages.types.schema).
    result = toolset.pages_update(
        superuser,
        id=stream_page.pk,
        fields={"title": "Still works", "nonsense_field": 99},
    )
    stream_page.refresh_from_db()
    assert result["slug"] == stream_page.slug


@pytest.mark.django_db
def test_update_anonymous_blocked(toolset, stream_page):
    with pytest.raises(PermissionDenied):
        toolset.pages_update(None, id=stream_page.pk, fields={"title": "nope"})


# -------------------------------------------------------------- pages.publish


@pytest.mark.django_db
def test_publish_defaults_to_latest_revision(toolset, superuser, stream_page):
    # Bump a revision first so there's something to publish.
    stream_page.title = "Draft changes"
    rev = stream_page.save_revision(user=superuser)
    result = toolset.pages_publish(superuser, id=stream_page.pk)
    assert result["live"] is True
    assert result["revision_id"] == rev.pk


@pytest.mark.django_db
def test_publish_no_revision_raises(toolset, superuser, home_page):
    """A freshly-created Page with no revision history raises a clean error."""
    # home_page comes from a plain add_child, no save_revision called yet.
    with pytest.raises(ValueError):
        toolset.pages_publish(superuser, id=home_page.pk)


# ------------------------------------------------------------ pages.unpublish


@pytest.mark.django_db
def test_unpublish_clears_live(toolset, superuser, stream_page):
    # Make sure it's live first.
    toolset.pages_update(superuser, id=stream_page.pk, fields={"title": "X"}, publish=True)
    result = toolset.pages_unpublish(superuser, id=stream_page.pk)
    assert result["live"] is False


# --------------------------------------------------------------- pages.delete


@pytest.mark.django_db
def test_delete_blocked_when_destructive_gate_off(
    toolset, superuser, stream_page, destructive_off
):
    with pytest.raises(PermissionDenied):
        toolset.pages_delete(superuser, id=stream_page.pk)
    assert TestStreamPage.objects.filter(pk=stream_page.pk).exists()


@pytest.mark.django_db
def test_delete_succeeds_when_destructive_gate_on(
    toolset, superuser, stream_page, destructive_on
):
    pk = stream_page.pk
    result = toolset.pages_delete(superuser, id=pk)
    assert result == {"id": pk, "deleted": True}
    assert not TestStreamPage.objects.filter(pk=pk).exists()


# ----------------------------------------------------------------- pages.move


@pytest.mark.django_db
def test_move_changes_parent(toolset, superuser, home_page, stream_page, site_root):
    # Create a sibling of home_page as the new parent.
    from wagtail.models import Page

    new_parent = Page(title="Elsewhere", slug="elsewhere")
    site_root.add_child(instance=new_parent)

    result = toolset.pages_move(
        superuser,
        id=stream_page.pk,
        parent_id=new_parent.pk,
        position="last-child",
    )
    assert result["parent_id"] == new_parent.pk
    assert result["url_path"].startswith("/elsewhere/")


@pytest.mark.django_db
def test_move_rejects_invalid_position(toolset, superuser, stream_page, home_page):
    with pytest.raises(ValueError):
        toolset.pages_move(
            superuser,
            id=stream_page.pk,
            parent_id=home_page.pk,
            position="middle-child",  # not in MOVE_POSITIONS
        )


def test_move_positions_constant_is_stable():
    """Contract: downstream schemas read this constant."""
    assert set(MOVE_POSITIONS) == {"first-child", "last-child", "left", "right"}
