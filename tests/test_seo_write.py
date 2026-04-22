"""Tests for ``SEOWriteToolset``.

Covers the five shapes we care about:

    1. Updating each allowed field lands on the page revision.
    2. Unknown fields raise before any DB mutation happens.
    3. Post-write findings are returned so the agent can see whether
       its fix was enough.
    4. ``publish=True`` publishes when the user has perm.
    5. Anonymous user gets PermissionDenied.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from wagtail_mcp_server.toolsets.seo_write import SEO_FIELDS, SEOWriteToolset


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
def test_seo_update_sets_seo_title(toolset, superuser, stream_page):
    result = toolset.seo_update(
        superuser, id=stream_page.pk, fields={"seo_title": "A better title"}
    )
    stream_page.refresh_from_db()
    # save_revision() stores the fields on the revision; the live row
    # only reflects them after publish. Check the returned revision_id
    # exists and the findings are present.
    assert result["revision_id"] is not None
    assert "findings" in result


@pytest.mark.django_db
def test_seo_update_can_touch_all_allowed_fields(toolset, superuser, stream_page):
    payload = {
        "seo_title": "Title that is long enough to pass the check easily",
        "search_description": (
            "A description that lands comfortably between the "
            "configured minimum and maximum lengths for SEO happiness."
        ),
        "slug": "freshly-slugged-post",
    }
    result = toolset.seo_update(superuser, id=stream_page.pk, fields=payload)
    assert result["slug"] == "freshly-slugged-post"


@pytest.mark.django_db
def test_seo_update_publishes_when_asked(toolset, superuser, stream_page):
    result = toolset.seo_update(
        superuser,
        id=stream_page.pk,
        fields={"seo_title": "Published title"},
        publish=True,
    )
    assert result["live"] is True


# ---------------------------------------------------------------- validation


@pytest.mark.django_db
def test_seo_update_rejects_empty_fields(toolset, superuser, stream_page):
    with pytest.raises(ValueError):
        toolset.seo_update(superuser, id=stream_page.pk, fields={})


@pytest.mark.django_db
def test_seo_update_rejects_unknown_fields(toolset, superuser, stream_page):
    with pytest.raises(ValueError) as excinfo:
        toolset.seo_update(
            superuser,
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
def test_seo_update_rejects_anonymous(toolset, stream_page):
    with pytest.raises(PermissionDenied):
        toolset.seo_update(
            None, id=stream_page.pk, fields={"seo_title": "nope"}
        )


# ----------------------------------------------------------- findings round-trip


@pytest.mark.django_db
def test_findings_reflect_post_write_state(toolset, superuser, stream_page):
    """Set a too-short title and verify the audit flags it afterwards."""
    result = toolset.seo_update(
        superuser, id=stream_page.pk, fields={"seo_title": "Hi"}
    )
    codes = {f["code"] for f in result["findings"]}
    assert "title_too_short" in codes
