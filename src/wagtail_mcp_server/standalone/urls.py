"""Empty URL conf for the standalone runtime.

Django requires ``ROOT_URLCONF`` to point at an importable module, but
the standalone server speaks MCP over stdio or SSE rather than over
HTTP routes. An empty ``urlpatterns`` is enough to satisfy the system
check.

Operators who want to mount the HTTP+SSE transport in front of nginx
should write their own settings module and include
``django_mcp_server.urls`` in their own urlconf -- the standalone
runtime is not the right place for production HTTP wiring.
"""

from __future__ import annotations

urlpatterns: list = []
