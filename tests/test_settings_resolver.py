"""Tests for the settings resolver.

Covers:
    - Defaults fill in when the user sets nothing.
    - Deep merge: overriding one key in a nested dict keeps the siblings.
    - Validation rejects unknown toolsets, auth backends, richtext formats,
      and write-validation modes.
    - Invariant: every write toolset is off by default.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from wagtail_mcp_server import settings as wms_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    wms_settings.reset_cache()
    yield
    wms_settings.reset_cache()


def test_defaults_applied_when_no_override():
    cfg = wms_settings.get_config()
    assert cfg["AUTH"]["BACKEND"] == "UserTokenAuth"
    assert cfg["AUTH"]["ALLOW_IMPERSONATION"] is False
    assert cfg["LIMITS"]["ALLOW_DESTRUCTIVE"] is False
    assert cfg["RICHTEXT_FORMAT"] == "html"
    assert cfg["WRITE_VALIDATION"] == "strict"
    # v0.5: OTel emission is on by default. Safe: no-op on hosts with
    # no SDK configured.
    assert cfg["AUDIT"]["EMIT_OTEL"] is True
    assert cfg["AUDIT"]["ENABLED"] is True
    assert cfg["AUDIT"]["RETENTION_DAYS"] == 90


def test_write_toolsets_off_by_default():
    cfg = wms_settings.get_config()
    for name in ("pages_write", "workflow", "media", "seo_write"):
        assert cfg["TOOLSETS"][name]["enabled"] is False, (
            f"Invariant broken: {name} must default to off."
        )


def test_read_toolsets_on_by_default():
    cfg = wms_settings.get_config()
    assert cfg["TOOLSETS"]["pages_query"]["enabled"] is True
    assert cfg["TOOLSETS"]["seo_query"]["enabled"] is True
    # v0.5: collections_query + snippets_query ship on-by-default, read-only.
    assert cfg["TOOLSETS"]["collections_query"]["enabled"] is True
    assert cfg["TOOLSETS"]["snippets_query"]["enabled"] is True


@override_settings(WAGTAIL_MCP_SERVER={"AUTH": {"BACKEND": "NotARealBackend"}})
def test_unknown_auth_backend_raises():
    wms_settings.reset_cache()
    with pytest.raises(ImproperlyConfigured, match="NotARealBackend"):
        wms_settings.get_config()


@override_settings(WAGTAIL_MCP_SERVER={"TOOLSETS": {"totally_made_up": {"enabled": True}}})
def test_unknown_toolset_raises():
    wms_settings.reset_cache()
    with pytest.raises(ImproperlyConfigured, match="totally_made_up"):
        wms_settings.get_config()


@override_settings(WAGTAIL_MCP_SERVER={"RICHTEXT_FORMAT": "markdown"})
def test_unknown_richtext_format_raises():
    wms_settings.reset_cache()
    with pytest.raises(ImproperlyConfigured, match="markdown"):
        wms_settings.get_config()


@override_settings(WAGTAIL_MCP_SERVER={"WRITE_VALIDATION": "loose"})
def test_unknown_write_validation_raises():
    wms_settings.reset_cache()
    with pytest.raises(ImproperlyConfigured, match="loose"):
        wms_settings.get_config()


@override_settings(
    WAGTAIL_MCP_SERVER={"TOOLSETS": {"pages_write": {"enabled": True}}}
)
def test_deep_merge_preserves_sibling_defaults():
    wms_settings.reset_cache()
    cfg = wms_settings.get_config()
    assert cfg["TOOLSETS"]["pages_write"]["enabled"] is True
    # Siblings still at default
    assert cfg["TOOLSETS"]["pages_query"]["enabled"] is True
    assert cfg["LIMITS"]["ALLOW_DESTRUCTIVE"] is False


def test_toolset_enabled_helper():
    assert wms_settings.toolset_enabled("pages_query") is True
    assert wms_settings.toolset_enabled("pages_write") is False
    assert wms_settings.toolset_enabled("does_not_exist") is False


def test_redirects_split_flag_defaults():
    """v0.5: ``redirects`` is the only toolset with the split-flag shape.

    Reads on by default; writes off. Both the combined ``toolset_enabled``
    helper (which ORs the two flags for the registration decision) and
    the per-side helpers must reflect this.
    """
    cfg = wms_settings.get_config()
    entry = cfg["TOOLSETS"]["redirects"]
    assert entry == {"enabled_read": True, "enabled_write": False}

    assert wms_settings.toolset_enabled("redirects") is True
    assert wms_settings.toolset_read_enabled("redirects") is True
    assert wms_settings.toolset_write_enabled("redirects") is False


@override_settings(
    WAGTAIL_MCP_SERVER={
        "TOOLSETS": {"redirects": {"enabled_read": False, "enabled_write": False}}
    }
)
def test_redirects_both_flags_off_disables_toolset():
    """If an operator turns both sides off, the toolset should be considered
    fully disabled so ``mcp.py`` skips the import."""
    wms_settings.reset_cache()
    assert wms_settings.toolset_enabled("redirects") is False
    assert wms_settings.toolset_read_enabled("redirects") is False
    assert wms_settings.toolset_write_enabled("redirects") is False


@override_settings(
    WAGTAIL_MCP_SERVER={
        "TOOLSETS": {"redirects": {"enabled_read": False, "enabled_write": True}}
    }
)
def test_redirects_write_only_still_enables_registration():
    """Asymmetric: writes on but reads off. ``toolset_enabled`` should still
    return True so the module is imported, and per-side gating keeps
    reads locked off at dispatch time."""
    wms_settings.reset_cache()
    assert wms_settings.toolset_enabled("redirects") is True
    assert wms_settings.toolset_read_enabled("redirects") is False
    assert wms_settings.toolset_write_enabled("redirects") is True
