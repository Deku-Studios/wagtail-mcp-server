"""End-to-end tests for :class:`RedirectsToolset`.

Exercises the split-flag config shape that is novel to v0.5:

    ``TOOLSETS.redirects.enabled_read``   (default True)
    ``TOOLSETS.redirects.enabled_write``  (default False)

Reads are expected to work out of the box for any authenticated user;
writes require the operator to flip ``enabled_write`` on *and* the
caller to hold the standard ``wagtailredirects.*_redirect`` Django
permissions; ``redirects.delete`` additionally requires
``LIMITS.ALLOW_DESTRUCTIVE`` (three-gate pattern, same as ``pages.delete``).

The toolset fixtures bind a caller via ``bind_user`` (see conftest).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.settings import reset_cache
from wagtail_mcp_server.toolsets.redirects import RedirectsToolset

# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def toolset():
    return RedirectsToolset()


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
def writes_on(settings):
    """Flip ``enabled_write`` on, leaving destructive gate closed.

    This is the common case for tests that want to create/update redirects
    but not delete them.
    """
    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {
            "redirects": {"enabled_read": True, "enabled_write": True},
        },
    }
    reset_cache()
    yield
    settings.WAGTAIL_MCP_SERVER = {}
    reset_cache()


@pytest.fixture
def writes_on_destructive_on(settings):
    """Open all three gates: write flag + destructive flag."""
    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {
            "redirects": {"enabled_read": True, "enabled_write": True},
        },
        "LIMITS": {"ALLOW_DESTRUCTIVE": True},
    }
    reset_cache()
    yield
    settings.WAGTAIL_MCP_SERVER = {}
    reset_cache()


@pytest.fixture
def sample_redirect(db):
    """A plain external-link redirect for the read tests."""
    from wagtail.contrib.redirects.models import Redirect

    return Redirect.objects.create(
        old_path="/old-thing", redirect_link="https://example.com/new"
    )


# --------------------------------------------------------------- redirects.list


@pytest.mark.django_db
def test_list_anonymous_blocked(toolset, bind_user):
    """Even reads require authentication -- the redirect table is admin data."""
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).redirects_list()


@pytest.mark.django_db
def test_list_returns_redirects(toolset, bind_user, superuser, sample_redirect):
    result = bind_user(toolset, superuser).redirects_list()
    assert result["total"] >= 1
    old_paths = {row["old_path"] for row in result["results"]}
    assert "/old-thing" in old_paths


# ---------------------------------------------------------------- redirects.get


@pytest.mark.django_db
def test_get_returns_redirect(toolset, bind_user, superuser, sample_redirect):
    payload = bind_user(toolset, superuser).redirects_get(id=sample_redirect.pk)
    assert payload is not None
    assert payload["id"] == sample_redirect.pk
    assert payload["redirect_link"] == "https://example.com/new"
    assert payload["redirect_page_id"] is None


@pytest.mark.django_db
def test_get_missing_returns_none(toolset, bind_user, superuser):
    assert bind_user(toolset, superuser).redirects_get(id=99999) is None


# ---------------------------------------------------- split-flag gating (writes)


@pytest.mark.django_db
def test_write_disabled_by_default_rejects_create(
    toolset, bind_user, superuser
):
    """Default config has writes OFF -- creating should be rejected even
    for a superuser. The split-flag shape means reads still work, but
    writes must be explicitly enabled."""
    reset_cache()
    with pytest.raises(PermissionDenied):
        bind_user(toolset, superuser).redirects_create(
            old_path="/forbidden",
            redirect_link="https://example.com/ignored",
        )


# ------------------------------------------------------------- redirects.create


@pytest.mark.django_db
def test_create_with_link_target(toolset, bind_user, superuser, writes_on):
    result = bind_user(toolset, superuser).redirects_create(
        old_path="/blog/old",
        redirect_link="https://example.com/blog/new",
        is_permanent=True,
    )
    assert result["old_path"] == "/blog/old"
    assert result["redirect_link"] == "https://example.com/blog/new"
    assert result["redirect_page_id"] is None
    assert result["is_permanent"] is True


@pytest.mark.django_db
def test_create_with_page_target(
    toolset, bind_user, superuser, writes_on, stream_page
):
    result = bind_user(toolset, superuser).redirects_create(
        old_path="/legacy-stream",
        redirect_page_id=stream_page.pk,
    )
    assert result["redirect_page_id"] == stream_page.pk
    assert result["redirect_link"] is None


@pytest.mark.django_db
def test_create_rejects_both_targets(toolset, bind_user, superuser, writes_on, stream_page):
    """XOR validation: exactly one of page or link is required."""
    with pytest.raises(ValueError, match="exactly one"):
        bind_user(toolset, superuser).redirects_create(
            old_path="/ambiguous",
            redirect_page_id=stream_page.pk,
            redirect_link="https://example.com/either",
        )


@pytest.mark.django_db
def test_create_rejects_neither_target(toolset, bind_user, superuser, writes_on):
    """XOR validation: refusing empty targets prevents a redirect that
    has no destination at all."""
    with pytest.raises(ValueError, match="exactly one"):
        bind_user(toolset, superuser).redirects_create(old_path="/dangling")


# ------------------------------------------------------------- redirects.update


@pytest.mark.django_db
def test_update_flips_target_from_page_to_link(
    toolset, bind_user, superuser, writes_on, stream_page
):
    """Switching from a page to an external link should clear the page FK.

    Contract: if both fields arrive on update, page id wins and link is
    cleared. If only link arrives, link is set and page is cleared. We
    test the second shape here: a redirect that used to point at a page
    now points at an external URL instead.
    """
    from wagtail.contrib.redirects.models import Redirect

    existing = Redirect.objects.create(
        old_path="/will-flip",
        redirect_page_id=stream_page.pk,
    )
    result = bind_user(toolset, superuser).redirects_update(
        id=existing.pk,
        redirect_link="https://example.com/external-now",
    )
    assert result["redirect_link"] == "https://example.com/external-now"
    assert result["redirect_page_id"] is None


# ------------------------------------------------------------- redirects.delete


@pytest.mark.django_db
def test_delete_requires_allow_destructive(
    toolset, bind_user, superuser, writes_on, sample_redirect
):
    """Three-gate pattern: even with writes enabled and superuser perms,
    delete still requires ``LIMITS.ALLOW_DESTRUCTIVE``."""
    with pytest.raises(PermissionDenied, match="ALLOW_DESTRUCTIVE"):
        bind_user(toolset, superuser).redirects_delete(id=sample_redirect.pk)

    # And the row is still there -- no partial mutation on rejection.
    from wagtail.contrib.redirects.models import Redirect

    assert Redirect.objects.filter(pk=sample_redirect.pk).exists()


@pytest.mark.django_db
def test_delete_when_all_gates_open(
    toolset, bind_user, superuser, writes_on_destructive_on, sample_redirect
):
    """With all three gates open, delete succeeds and the row is gone."""
    pk = sample_redirect.pk
    result = bind_user(toolset, superuser).redirects_delete(id=pk)
    assert result["deleted"] is True
    assert result["redirect"]["id"] == pk

    from wagtail.contrib.redirects.models import Redirect

    assert not Redirect.objects.filter(pk=pk).exists()
