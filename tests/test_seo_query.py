"""End-to-end tests for ``SEOQueryToolset`` and its audit rules.

Toolset instances are bound to a user via ``bind_user`` (see conftest).
``seo.*`` query tools treat an unauthenticated caller as the "public"
view, so most happy-path tests use ``user=None``.
"""

from __future__ import annotations

import pytest

from wagtail_mcp_server.toolsets.seo_query import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    TITLE_MAX,
    TITLE_MIN,
    SEOQueryToolset,
)


@pytest.fixture
def toolset():
    return SEOQueryToolset()


# -------------------------------------------------------------------- seo.get


@pytest.mark.django_db
def test_seo_get_by_id_returns_payload(toolset, bind_user, stream_page):
    payload = bind_user(toolset, None).seo_get(id=stream_page.pk)
    assert payload is not None
    assert payload["page"]["id"] == stream_page.pk
    assert "findings" in payload
    assert "canonical_url" in payload


@pytest.mark.django_db
def test_seo_get_requires_one_locator(toolset, bind_user):
    with pytest.raises(ValueError):
        bind_user(toolset, None).seo_get()


@pytest.mark.django_db
def test_seo_get_missing_page_returns_none(toolset, bind_user, home_page):
    assert bind_user(toolset, None).seo_get(id=999_999) is None


# ------------------------------------------------------------------ audit rules


@pytest.mark.django_db
def test_audit_flags_title_too_short(toolset, bind_user, stream_page):
    stream_page.title = "Hi"  # below TITLE_MIN
    stream_page.save_revision().publish()
    payload = bind_user(toolset, None).seo_get(id=stream_page.pk)
    codes = {f["code"] for f in payload["findings"]}
    assert "title_too_short" in codes


@pytest.mark.django_db
def test_audit_flags_description_too_long(toolset, bind_user, stream_page):
    stream_page.search_description = "x" * (DESCRIPTION_MAX + 5)
    stream_page.save_revision().publish()
    payload = bind_user(toolset, None).seo_get(id=stream_page.pk)
    codes = {f["code"] for f in payload["findings"]}
    assert "description_too_long" in codes


@pytest.mark.django_db
def test_audit_flags_description_missing(toolset, bind_user, stream_page):
    stream_page.search_description = ""
    stream_page.save_revision().publish()
    payload = bind_user(toolset, None).seo_get(id=stream_page.pk)
    codes = {f["code"] for f in payload["findings"]}
    assert "description_missing" in codes


@pytest.mark.django_db
def test_audit_clean_title_produces_no_title_finding(
    toolset, bind_user, stream_page
):
    stream_page.seo_title = "A" * ((TITLE_MIN + TITLE_MAX) // 2)
    stream_page.search_description = "b" * ((DESCRIPTION_MIN + DESCRIPTION_MAX) // 2)
    stream_page.save_revision().publish()
    payload = bind_user(toolset, None).seo_get(id=stream_page.pk)
    codes = {f["code"] for f in payload["findings"]}
    assert "title_too_short" not in codes
    assert "title_too_long" not in codes
    assert "description_missing" not in codes


# ------------------------------------------------------------------ seo.audit


@pytest.mark.django_db
def test_audit_returns_only_pages_with_findings(toolset, bind_user, stream_page):
    # Empty search_description + default title triggers at least description_missing.
    result = bind_user(toolset, None).seo_audit(limit=100)
    assert result["total"] >= 1
    ids = {item["page"]["id"] for item in result["items"]}
    assert stream_page.pk in ids


@pytest.mark.django_db
def test_audit_min_severity_filters_info_findings(
    toolset, bind_user, stream_page
):
    # Warn-or-higher filter must exclude pages whose only finding is info.
    stream_page.seo_title = "A" * ((TITLE_MIN + TITLE_MAX) // 2)
    stream_page.search_description = "b" * (DESCRIPTION_MIN - 5)  # too_short = info
    stream_page.save_revision().publish()

    result = bind_user(toolset, None).seo_audit(limit=100, min_severity="warn")
    ids = {item["page"]["id"] for item in result["items"]}
    assert stream_page.pk not in ids


@pytest.mark.django_db
def test_audit_filters_by_type(toolset, bind_user, stream_page):
    result = bind_user(toolset, None).seo_audit(
        type="wagtail_mcp_server_testapp.TestStreamPage",
    )
    assert all(
        item["page"]["page_type"].endswith(".TestStreamPage")
        for item in result["items"]
    )


# ---------------------------------------------------------------- seo.sitemap


@pytest.mark.django_db
def test_sitemap_returns_live_pages(toolset, bind_user, stream_page):
    result = bind_user(toolset, None).seo_sitemap(limit=50)
    assert "items" in result
    assert "total" in result


# ------------------------------------------------------------------ RULES contract


def test_rules_table_severities_are_stable():
    """The (code, severity) contract is consumed by downstream tools."""
    assert SEOQueryToolset.RULES["title_missing"] == "error"
    assert SEOQueryToolset.RULES["title_too_short"] == "warn"
    assert SEOQueryToolset.RULES["description_too_short"] == "info"
