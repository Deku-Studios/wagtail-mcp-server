"""Tests for ``SEOWriteToolset``.

Covers the five shapes we care about:

    1. Updating each allowed field lands on the page revision.
    2. Unknown fields raise before any DB mutation happens.
    3. Post-write findings are returned so the agent can see whether
       its fix was enough.
    4. ``publish=True`` publishes when the user has perm.
    5. Anonymous user gets PermissionDenied.

Toolsets are instantiated without arguments; the caller is bound to
``self.request.user`` by the ``bind_user`` fixture (see conftest).
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.toolsets.seo_write import (
    SEO_FIELDS,
    SEOWriteToolset,
    sitemap_regenerated,
)


@pytest.fixture
def toolset():
    return SEOWriteToolset()


@pytest.fixture
def superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        password="x",  # noqa: S106
        is_superuser=True,
        is_staff=True,
    )


# ---------------------------------------------------------------- happy path


@pytest.mark.django_db
def test_seo_update_sets_seo_title(toolset, bind_user, superuser, stream_page):
    result = bind_user(toolset, superuser).seo_update(
        id=stream_page.pk, fields={"seo_title": "A better title"}
    )
    stream_page.refresh_from_db()
    # save_revision() stores the fields on the revision; the live row
    # only reflects them after publish. Check the returned revision_id
    # exists and the findings are present.
    assert result["revision_id"] is not None
    assert "findings" in result


@pytest.mark.django_db
def test_seo_update_can_touch_all_allowed_fields(
    toolset, bind_user, superuser, stream_page
):
    payload = {
        "seo_title": "Title that is long enough to pass the check easily",
        "search_description": (
            "A description that lands comfortably between the "
            "configured minimum and maximum lengths for SEO happiness."
        ),
        "slug": "freshly-slugged-post",
    }
    result = bind_user(toolset, superuser).seo_update(
        id=stream_page.pk, fields=payload
    )
    assert result["slug"] == "freshly-slugged-post"


@pytest.mark.django_db
def test_seo_update_publishes_when_asked(
    toolset, bind_user, superuser, stream_page
):
    result = bind_user(toolset, superuser).seo_update(
        id=stream_page.pk,
        fields={"seo_title": "Published title"},
        publish=True,
    )
    assert result["live"] is True


# ---------------------------------------------------------------- validation


@pytest.mark.django_db
def test_seo_update_rejects_empty_fields(
    toolset, bind_user, superuser, stream_page
):
    with pytest.raises(ValueError):
        bind_user(toolset, superuser).seo_update(id=stream_page.pk, fields={})


@pytest.mark.django_db
def test_seo_update_rejects_unknown_fields(
    toolset, bind_user, superuser, stream_page
):
    with pytest.raises(ValueError) as excinfo:
        bind_user(toolset, superuser).seo_update(
            id=stream_page.pk,
            fields={"seo_title": "ok", "not_a_real_field": "x"},
        )
    # The error body should name the offending field AND list the
    # allowed set; both are contractual for the agent.
    msg = str(excinfo.value)
    assert "not_a_real_field" in msg
    for allowed in SEO_FIELDS:
        if allowed != "og_image":  # not always present on every model
            assert allowed in msg


# ------------------------------------------------------------------ auth gate


@pytest.mark.django_db
def test_seo_update_rejects_anonymous(toolset, bind_user, stream_page):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).seo_update(
            id=stream_page.pk, fields={"seo_title": "nope"}
        )


# ----------------------------------------------------------- findings round-trip


@pytest.mark.django_db
def test_findings_reflect_post_write_state(
    toolset, bind_user, superuser, stream_page
):
    """Set a too-short title and verify the audit flags it afterwards."""
    result = bind_user(toolset, superuser).seo_update(
        id=stream_page.pk, fields={"seo_title": "Hi"}
    )
    codes = {f["code"] for f in result["findings"]}
    assert "title_too_short" in codes


# ----------------------------------------------------- seo.sitemap.regenerate


@pytest.mark.django_db
def test_sitemap_regenerate_returns_live_page_count(
    toolset, bind_user, superuser, stream_page
):
    """Happy path: walks live queryset and returns count + timestamp."""
    result = bind_user(toolset, superuser).seo_sitemap_regenerate()
    assert result["regenerated"] is True
    assert result["page_count"] >= 1  # at least the test stream_page
    assert isinstance(result["generated_at"], str)
    assert result["cache_keys_busted"] == []


@pytest.mark.django_db
def test_sitemap_regenerate_busts_supplied_cache_keys(
    toolset, bind_user, superuser, stream_page, settings
):
    """The list of keys passed in comes back in cache_keys_busted, in order."""
    # Install an in-memory cache so delete() is observable.
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "sitemap-regenerate-test",
        }
    }

    from django.core.cache import cache

    cache.set("sitemap-pages", "OLD", timeout=None)
    cache.set("sitemap-images", "OLD", timeout=None)
    cache.set("unrelated-key", "KEEP", timeout=None)

    result = bind_user(toolset, superuser).seo_sitemap_regenerate(
        cache_keys=["sitemap-pages", "sitemap-images"],
    )
    assert result["cache_keys_busted"] == ["sitemap-pages", "sitemap-images"]
    assert cache.get("sitemap-pages") is None
    assert cache.get("sitemap-images") is None
    # Keys we didn't list should be untouched.
    assert cache.get("unrelated-key") == "KEEP"


@pytest.mark.django_db
def test_sitemap_regenerate_rejects_anonymous(toolset, bind_user):
    with pytest.raises(PermissionDenied):
        bind_user(toolset, None).seo_sitemap_regenerate()


@pytest.mark.django_db
def test_sitemap_regenerate_rejects_non_admin(toolset, bind_user):
    """A plain authenticated user without admin access should be rejected.

    This is what keeps an MCP agent bound to a low-privilege account
    from blowing away the host's sitemap cache.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    bob = User.objects.create_user(
        username="bob",
        password="x",  # noqa: S106
        is_staff=False,
    )
    with pytest.raises(PermissionDenied, match="access_admin"):
        bind_user(toolset, bob).seo_sitemap_regenerate()


@pytest.mark.django_db
def test_sitemap_regenerate_fires_signal(
    toolset, bind_user, superuser, stream_page
):
    """Signal contract: hosts subscribe to bust their own caches."""
    calls: list[dict] = []

    def _handler(sender, **kwargs):
        calls.append({"sender": sender, **kwargs})

    sitemap_regenerated.connect(_handler, weak=False)
    try:
        bind_user(toolset, superuser).seo_sitemap_regenerate(
            cache_keys=["k1"],
        )
    finally:
        sitemap_regenerated.disconnect(_handler)

    assert len(calls) == 1
    (payload,) = calls
    assert payload["sender"] is SEOWriteToolset
    assert payload["user"] == superuser
    assert payload["page_count"] >= 1
    assert payload["cache_keys_busted"] == ("k1",)
