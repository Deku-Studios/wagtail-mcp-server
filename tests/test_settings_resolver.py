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
