"""URL routing for wagtail-mcp-server.

This module exposes the MCP transport endpoints. Mount it under whatever
path the host project prefers (``/mcp/`` is the canonical choice):

    path("mcp/", include("wagtail_mcp_server.urls")),

The actual endpoint shape (HTTP+SSE, JSON-RPC, etc.) is delegated to
django-mcp-server; this module simply wires its routes into the host app.
"""

from __future__ import annotations

from django.urls import path
from django.views.generic import View

app_name = "wagtail_mcp_server"


class _Placeholder(View):
    """Temporary hook while django-mcp-server wiring lands in v0.2."""

    def get(self, request, *args, **kwargs):  # noqa: ARG002
        from django.http import JsonResponse  # noqa: PLC0415

        return JsonResponse(
            {
                "name": "wagtail-mcp-server",
                "status": "scaffold",
                "message": (
                    "MCP transport wiring is implemented in v0.2. "
                    "This placeholder confirms the app is mounted."
                ),
            }
        )


urlpatterns = [
    path("", _Placeholder.as_view(), name="root"),
]
