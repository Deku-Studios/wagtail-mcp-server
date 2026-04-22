"""HTTP-level smoke tests for the MCP endpoint.

These tests exercise the full Django/DRF stack, not the toolsets
directly. They prove that:

    1. The URL conf mounts :class:`MCPServerStreamableHttpView` under
       ``/mcp/`` (no doubled prefix from upstream ``mcp_server.urls``).
    2. :class:`wagtail_mcp_server.auth.UserTokenDRFAuth` is wired as the
       default authentication class and rejects anonymous + bogus
       requests with HTTP 401.
    3. DRF's ``WWW-Authenticate`` header is populated so HTTP clients
       know to surface a bearer prompt.

What these tests deliberately do **not** cover:
    - A full tools/list round-trip with a seeded ``UserMcpToken`` row.
      That will land in the 0.5.0 integration pass once the tag is cut
      and the host project is pinned; requiring it here would tie every
      library release to a synthesized JSON-RPC envelope we do not yet
      need.
    - The stdio transport (``WAGTAIL_MCP_SERVER_TOKEN``). HTTP is the
      only transport shipped in 0.4.0; the env-var path is covered by
      ``test_auth.py`` at the backend level.
"""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def client() -> Client:
    return Client()


# ------------------------------------------------------------------ no-auth


@pytest.mark.django_db
def test_mcp_endpoint_rejects_request_with_no_authorization_header(client):
    """An empty Authorization header short-circuits to 401 without DB work.

    ``UserTokenDRFAuth.authenticate`` returns ``None`` when no Bearer
    header is present, which -- combined with ``IsAuthenticated`` on the
    view -- yields DRF's "credentials were not provided" 401. We assert
    on the status plus the presence of a ``WWW-Authenticate`` realm so
    clients can render a bearer prompt automatically.
    """
    response = client.post("/mcp/", data="{}", content_type="application/json")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate", "").startswith("Bearer")


@pytest.mark.django_db
def test_mcp_endpoint_rejects_get_with_no_auth(client):
    """The same gate applies to any method; GET also bounces at 401."""
    response = client.get("/mcp/")
    assert response.status_code == 401


# --------------------------------------------------------------- bogus auth


@pytest.mark.django_db
def test_mcp_endpoint_rejects_bogus_bearer_token(client):
    """A syntactically valid-looking Bearer that resolves to nothing = 401.

    This exercises the full happy path of
    ``UserTokenDRFAuth.authenticate``: extract the header, hand off to
    ``UserTokenAuth``, let it query ``UserMcpToken`` (the table is
    migrated because of the ``django_db`` fixture), and raise
    ``AuthenticationFailed`` on lookup miss. DRF turns that into a 401
    with a descriptive body.
    """
    response = client.post(
        "/mcp/",
        data="{}",
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer not-a-real-token",
    )
    assert response.status_code == 401
    assert b"Invalid or revoked token" in response.content


@pytest.mark.django_db
def test_mcp_endpoint_rejects_malformed_authorization_header(client):
    """Non-Bearer schemes are treated as missing credentials, not errors.

    ``UserTokenDRFAuth.authenticate`` returns ``None`` for anything that
    does not start with ``Bearer ``, so DRF treats the request as
    unauthenticated and the ``IsAuthenticated`` permission yields 401.
    """
    response = client.post(
        "/mcp/",
        data="{}",
        content_type="application/json",
        HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz",
    )
    assert response.status_code == 401
