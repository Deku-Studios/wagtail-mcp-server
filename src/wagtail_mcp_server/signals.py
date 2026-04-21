"""Django signal handlers for wagtail-mcp-server.

Currently empty. Reserved for v0.2, which will wire Wagtail page lifecycle
signals (``page_published``, ``page_unpublished``, workflow transitions)
into the audit trail so agent-initiated state changes emit telemetry even
when the change happens via a non-MCP path.
"""

from __future__ import annotations

# Intentional: no handlers yet. AppConfig.ready still imports this module
# so connecting a handler here is a one-line change later.
