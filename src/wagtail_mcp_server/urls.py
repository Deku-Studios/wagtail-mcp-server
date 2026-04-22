"""URL routing for wagtail-mcp-server.

This module exposes the MCP Streamable HTTP endpoint on the empty path
so the host project can mount it wherever it wants without the library
imposing a second prefix:

    path("mcp/", include("wagtail_mcp_server.urls")),

Auth is pulled from ``WAGTAIL_MCP_SERVER_AUTH_CLASSES`` (preferred) or
``DJANGO_MCP_AUTHENTICATION_CLASSES`` (the upstream django-mcp-server
setting). If neither is set the library defaults to its own
:class:`wagtail_mcp_server.auth.UserTokenDRFAuth`, which is the
recommended production backend. Set the setting to an empty list to
disable auth entirely (development only).

We intentionally do **not** ``include("mcp_server.urls")`` upstream,
because that module hard-codes a ``DJANGO_MCP_ENDPOINT`` default of
``"mcp"`` and would cause the endpoint to resolve at ``/mcp/mcp/`` under
our canonical ``/mcp/`` mount.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import path
from django.utils.module_loading import import_string
from mcp_server.views import MCPServerStreamableHttpView
from rest_framework.permissions import IsAuthenticated

app_name = "wagtail_mcp_server"


def _resolve_auth_classes() -> list[type]:
    """Resolve the configured DRF auth classes for the MCP endpoint.

    Resolution order:
        1. ``WAGTAIL_MCP_SERVER_AUTH_CLASSES`` (list of dotted paths)
        2. ``DJANGO_MCP_AUTHENTICATION_CLASSES`` (upstream setting)
        3. Default: ``["wagtail_mcp_server.auth.UserTokenDRFAuth"]``

    An explicit empty list disables auth (useful in test settings).
    """
    if hasattr(settings, "WAGTAIL_MCP_SERVER_AUTH_CLASSES"):
        dotted = settings.WAGTAIL_MCP_SERVER_AUTH_CLASSES
    elif hasattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES"):
        dotted = settings.DJANGO_MCP_AUTHENTICATION_CLASSES
    else:
        dotted = ["wagtail_mcp_server.auth.UserTokenDRFAuth"]
    return [import_string(cls) for cls in dotted]


_auth_classes = _resolve_auth_classes()

urlpatterns = [
    path(
        "",
        MCPServerStreamableHttpView.as_view(
            permission_classes=[IsAuthenticated] if _auth_classes else [],
            authentication_classes=_auth_classes,
        ),
        name="endpoint",
    ),
]
