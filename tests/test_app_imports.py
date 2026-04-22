"""Smoke test: the app and all of its toolsets import cleanly.

Regression gate for the "on by default" invariant: the scaffold stubs
must import without side effects, or AppConfig.ready will blow up at
Django startup in any host project that installs us.
"""

from __future__ import annotations

import importlib


def test_all_toolsets_importable():
    for name in (
        "pages_query",
        "pages_write",
        "workflow",
        "media",
        "seo_query",
        "seo_write",
    ):
        mod = importlib.import_module(f"wagtail_mcp_server.toolsets.{name}")
        assert mod is not None


def test_registry_map_is_complete():
    from wagtail_mcp_server.registry import TOOLSET_MAP
    from wagtail_mcp_server.settings import DEFAULTS

    config_toolsets = set(DEFAULTS["TOOLSETS"].keys())
    registry_toolsets = set(TOOLSET_MAP.keys())
    assert config_toolsets == registry_toolsets, (
        "Toolset names in DEFAULTS and TOOLSET_MAP must match exactly."
    )


def test_models_import():
    from wagtail_mcp_server.models import AgentScratchpad, ToolCall, UserMcpToken
    assert UserMcpToken is not None
    assert ToolCall is not None
    assert AgentScratchpad is not None


def test_cli_import():
    from wagtail_mcp_server.cli import main
    assert main is not None


def test_register_enabled_toolsets_runs_cleanly(settings):
    """AppConfig.ready path: registration must succeed with every toolset on."""
    from wagtail_mcp_server.registry import register_enabled_toolsets
    from wagtail_mcp_server.settings import reset_cache

    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {
            "pages_query": {"enabled": True},
            "pages_write": {"enabled": True},
            "seo_query": {"enabled": True},
            "seo_write": {"enabled": True},
            "workflow": {"enabled": True},
            "media": {"enabled": True},
        },
    }
    reset_cache()
    try:
        register_enabled_toolsets()  # must not raise
    finally:
        settings.WAGTAIL_MCP_SERVER = {}
        reset_cache()
