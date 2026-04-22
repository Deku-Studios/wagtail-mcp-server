"""Smoke test: the app and all of its toolsets import cleanly.

Regression gate for the "on by default" invariant: the scaffold stubs
must import without side effects, or AppConfig.ready will blow up at
Django startup in any host project that installs us.

Also covers the config-aware loader in ``wagtail_mcp_server.mcp`` that
django-mcp-server's ``autodiscover_modules('mcp')`` pass triggers at
startup: when a toolset is enabled, its module must be importable and
its slug must end up in :func:`wagtail_mcp_server.registry.loaded_toolsets`.
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


def test_load_enabled_runs_cleanly(settings):
    """``_load_enabled`` must not raise when every toolset is on.

    This is the replacement for the old ``register_enabled_toolsets``
    smoke test; after the 0.4.0 refactor, toolset registration is a
    side effect of importing the class (the ``ToolsetMeta`` metaclass
    does the bookkeeping), and :mod:`wagtail_mcp_server.mcp` gates those
    imports on the ``WAGTAIL_MCP_SERVER.TOOLSETS`` config. The metaclass
    is idempotent, so re-running the loader in a test is safe.
    """
    from wagtail_mcp_server.mcp import _load_enabled
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
        loaded = _load_enabled()
        assert set(loaded) == {
            "pages_query",
            "pages_write",
            "seo_query",
            "seo_write",
            "workflow",
            "media",
        }
    finally:
        settings.WAGTAIL_MCP_SERVER = {}
        reset_cache()


def test_load_enabled_skips_disabled(settings):
    """Toolsets explicitly set to ``enabled: False`` must not load.

    ``pages_query`` and ``seo_query`` are on in the shipped defaults, so
    an effective "only pages_query" setup must turn the sibling read
    toolset off explicitly. This exercises the deep-merge path and proves
    the loader respects an explicit opt-out.
    """
    from wagtail_mcp_server.mcp import _load_enabled
    from wagtail_mcp_server.settings import reset_cache

    settings.WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {
            "pages_query": {"enabled": True},
            "seo_query": {"enabled": False},
            # pages_write/seo_write/workflow/media default to disabled.
        },
    }
    reset_cache()
    try:
        loaded = _load_enabled()
        assert loaded == ["pages_query"]
    finally:
        settings.WAGTAIL_MCP_SERVER = {}
        reset_cache()


def test_loaded_toolsets_snapshot_returns_list():
    """``loaded_toolsets()`` returns the boot-time frozen list.

    Its contents depend on the test-settings ``WAGTAIL_MCP_SERVER`` dict
    that was active at import of :mod:`wagtail_mcp_server.mcp`, so we
    only assert the public shape here.
    """
    from wagtail_mcp_server.registry import loaded_toolsets

    result = loaded_toolsets()
    assert isinstance(result, list)
    for slug in result:
        assert isinstance(slug, str)
