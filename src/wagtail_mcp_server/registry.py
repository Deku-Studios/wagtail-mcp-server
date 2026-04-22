"""Toolset registration has moved to :mod:`wagtail_mcp_server.mcp`.

This module is kept as a stable public import path for operators who
want to introspect the toolset <-> class mapping outside of MCP
dispatch. The real registration side-effect fires when
``mcp_server.apps.McpServerConfig.ready()`` calls
``autodiscover_modules('mcp')`` on every installed app, which imports
:mod:`wagtail_mcp_server.mcp` and triggers the conditional loads.

In v0.1 this module held a scaffold no-op. That no-op is gone; the
registry decision is now "if imported, then registered" by the
``MCPToolset`` metaclass, and conditional importing lives in
``mcp.py`` alongside the config reader.
"""

from __future__ import annotations

from .mcp import _IMPORTS as TOOLSET_MAP  # re-export for compatibility
from .mcp import _LOADED_TOOLSETS

__all__ = ["TOOLSET_MAP", "loaded_toolsets"]


def loaded_toolsets() -> list[str]:
    """Return the slugs of toolsets that were successfully loaded.

    The list is frozen at Django startup; once the app config is
    evaluated no further toolsets can be added without a process
    restart. Useful for health endpoints and debug shells that want to
    verify the active MCP surface.
    """
    return list(_LOADED_TOOLSETS)
