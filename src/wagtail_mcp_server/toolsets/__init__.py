"""Toolsets exposed over MCP.

Read toolsets (on by default):
    - :mod:`wagtail_mcp_server.toolsets.pages_query`
    - :mod:`wagtail_mcp_server.toolsets.seo_query`

Write toolsets (off by default):
    - :mod:`wagtail_mcp_server.toolsets.pages_write`
    - :mod:`wagtail_mcp_server.toolsets.workflow`
    - :mod:`wagtail_mcp_server.toolsets.media`
    - :mod:`wagtail_mcp_server.toolsets.seo_write`

Invariant: every write toolset is off by default. Adding a new write
toolset that is on by default is not a backward-compatible change.
"""
