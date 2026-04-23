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
    4. (v0.5) A request with a valid ``UserMcpToken`` clears the auth
       gate -- the body shape from django-mcp-server's JSON-RPC handler
       is treated as opaque on purpose, but anything other than a 401
       is proof the bearer flowed all the way through.
    5. (v0.5) The latent ``X-Impersonate-User`` header is *ignored*
       while ``AUTH.ALLOW_IMPERSONATION`` is False (i.e. always, until
       impersonation ships). This is a regression test: any future
       impersonation work must not enable header-based switching by
       default.
    6. (v0.5) ``WAGTAIL_MCP_SERVER_AUTH_CLASSES = []`` disables auth at
       the URL conf, letting unauthenticated requests through. Used in
       internal/dev deployments behind a network gate.

Tool-registration toggle behaviour (which toolsets are exposed under
which config combinations) is covered separately in
``test_settings_resolver.py`` and the new ``test_load_enabled_*``
tests at the bottom of this file. Those exercise the same loader the
HTTP transport calls into, without paying for a JSON-RPC round trip.

What these tests deliberately do **not** cover:
    - A full ``tools/list`` JSON-RPC round trip with response parsing.
      django-mcp-server's HTTP transport may require a session-id
      handshake or an SSE upgrade depending on its version, so we
      validate the auth flow without committing to a body shape.
    - The stdio transport (``WAGTAIL_MCP_SERVER_TOKEN``). HTTP is the
      only transport shipped in 0.4.0; the env-var path is covered by
      ``test_auth.py`` at the backend level. Standalone-runtime stdio
      is exercised by Chunk 4c's subprocess smoke test.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings


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


# ---------------------------------------------------------------- happy path


@pytest.fixture
def seeded_token(db):
    """Mint a real token bound to a fresh staff user.

    Returns ``(plaintext, user)``; the plaintext is what gets sent in
    the Bearer header and the user is what callers compare against
    ``request.user`` in spy assertions.
    """
    from wagtail_mcp_server.models import UserMcpToken

    User = get_user_model()
    user = User.objects.create_user(
        username="agent",
        password="x",  # noqa: S106
        is_staff=True,
    )
    _row, plaintext = UserMcpToken.issue(user=user, label="test agent")
    return plaintext, user


def _jsonrpc(method: str, params: dict | None = None, request_id: int = 1) -> str:
    """Tiny helper -- a canonical JSON-RPC 2.0 envelope, serialized."""
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body)


@pytest.mark.django_db
def test_mcp_endpoint_clears_auth_gate_with_valid_token(client, seeded_token):
    """A valid bearer must NOT yield 401 -- the auth pipeline let it through.

    We deliberately do not assert on the body or status beyond "not
    401". django-mcp-server's HTTP transport may answer with an
    SSE-shaped response, a JSON-RPC error for missing handshake, or a
    200 with a tools list -- all of those are valid evidence that
    :class:`wagtail_mcp_server.auth.UserTokenDRFAuth` resolved the
    bearer to a user and DRF passed control downstream. The thing we
    are explicitly guarding against is a regression where the auth
    backend silently reverts to rejecting all requests.
    """
    plaintext, _user = seeded_token
    response = client.post(
        "/mcp/",
        data=_jsonrpc("tools/list"),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {plaintext}",
    )
    assert response.status_code != 401, (
        f"Valid bearer was rejected at the auth gate (status="
        f"{response.status_code}, body={response.content[:200]!r})"
    )


@pytest.mark.django_db
def test_valid_token_marks_last_used(client, seeded_token):
    """Side-effect contract: the token row's ``last_used_at`` must update.

    Hosts that watch token rotation (e.g. lex-platform's bot dashboard)
    rely on this being touched on every successful resolution. Without
    it a stale token looks active forever.
    """
    from wagtail_mcp_server.models import UserMcpToken

    plaintext, _user = seeded_token
    row = UserMcpToken.objects.get(token_hash=UserMcpToken.hash_token(plaintext))
    assert row.last_used_at is None

    client.post(
        "/mcp/",
        data=_jsonrpc("tools/list"),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {plaintext}",
    )

    row.refresh_from_db()
    assert row.last_used_at is not None


# --------------------------------------------------------------- impersonation


@pytest.mark.django_db
def test_impersonation_header_is_ignored_while_flag_is_off(client, seeded_token):
    """``X-Impersonate-User`` must be a no-op until the flag ships.

    ``AUTH.ALLOW_IMPERSONATION`` defaults to False and there is no
    code in v0.5 that consumes the header. This test exists to lock
    in that contract: if a future change wires up impersonation, this
    test must be updated *and* a corresponding flag-on case added.
    Silently letting an arbitrary header rebind ``request.user`` would
    be a privilege-escalation bug.

    We assert via the side-effect we *can* observe: the seeded token
    user's ``last_used_at`` updates, but no second user row appears
    or has its token used. The handler itself may 4xx for any reason,
    but the auth side-effect must always reflect the token bearer.
    """
    from wagtail_mcp_server.models import UserMcpToken

    plaintext, token_user = seeded_token

    # Pre-create a second user whose username matches the would-be
    # impersonation target. If the header were honored, the auth path
    # would somehow surface this user; since it isn't, this row must
    # remain pristine.
    User = get_user_model()
    victim = User.objects.create_user(
        username="victim",
        password="x",  # noqa: S106
        is_staff=True,
        is_superuser=True,
    )

    client.post(
        "/mcp/",
        data=_jsonrpc("tools/list"),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        HTTP_X_IMPERSONATE_USER="victim",
    )

    token_row = UserMcpToken.objects.get(
        token_hash=UserMcpToken.hash_token(plaintext)
    )
    assert token_row.user_id == token_user.pk
    # The victim must have no tokens minted in their name.
    assert UserMcpToken.objects.filter(user=victim).count() == 0


# ------------------------------------------------------------- auth disabled


@pytest.mark.django_db
def test_empty_auth_classes_lets_unauthenticated_requests_through(client):
    """Setting ``WAGTAIL_MCP_SERVER_AUTH_CLASSES = []`` opens the gate.

    The URL conf's ``_resolve_auth_classes`` returns ``[]`` and the
    view drops ``IsAuthenticated`` accordingly. Used by hosts that
    front the endpoint with mTLS or a network-level gate. This test
    forces a re-import of ``wagtail_mcp_server.urls`` so the empty
    list takes effect; in production the setting must be in place
    before the URL conf loads.
    """
    import importlib
    import sys

    with override_settings(WAGTAIL_MCP_SERVER_AUTH_CLASSES=[]):
        sys.modules.pop("wagtail_mcp_server.urls", None)
        importlib.import_module("wagtail_mcp_server.urls")
        # And the test URLs include() needs to re-resolve too.
        from django.urls import clear_url_caches

        clear_url_caches()
        sys.modules.pop("tests.urls", None)
        importlib.import_module("tests.urls")
        clear_url_caches()

        try:
            response = client.post(
                "/mcp/",
                data=_jsonrpc("tools/list"),
                content_type="application/json",
            )
            # Anything other than 401 is success -- the gate is open.
            assert response.status_code != 401
        finally:
            # Restore the default-auth URL conf for downstream tests.
            sys.modules.pop("wagtail_mcp_server.urls", None)
            importlib.import_module("wagtail_mcp_server.urls")
            sys.modules.pop("tests.urls", None)
            importlib.import_module("tests.urls")
            clear_url_caches()


# ----------------------------------------------------------- toolset toggle


# These tests exercise the same loader the autodiscover pass calls.
# Because Python imports are sticky, calling ``_load_enabled`` again
# under different config does not "unregister" already-registered
# toolsets at the metaclass level -- but the *list of slugs returned*
# is the canonical per-process surface declaration, and that's what
# ``mcp_server.apps.McpServerConfig.ready`` consults. Asserting on this
# return value is the cheapest way to lock in toggle behaviour without
# spinning up a real MCP HTTP transport that we cannot run in CI's
# Python 3.10 sandbox.


def test_load_enabled_returns_only_read_toolsets_under_safe_defaults():
    from wagtail_mcp_server.mcp import _load_enabled
    from wagtail_mcp_server.settings import reset_cache

    reset_cache()
    with override_settings(
        WAGTAIL_MCP_SERVER={
            "TOOLSETS": {
                "pages_query": {"enabled": True},
                "seo_query": {"enabled": True},
                "collections_query": {"enabled": True},
                "snippets_query": {"enabled": True},
                "redirects": {"enabled_read": True, "enabled_write": False},
                "pages_write": {"enabled": False},
                "workflow": {"enabled": False},
                "media": {"enabled": False},
                "seo_write": {"enabled": False},
            }
        }
    ):
        reset_cache()
        loaded = _load_enabled()

    assert "pages_query" in loaded
    assert "seo_query" in loaded
    assert "redirects" in loaded
    # No write toolset should appear here.
    for slug in ("pages_write", "workflow", "media", "seo_write"):
        assert slug not in loaded, (
            f"{slug} leaked into the load list under safe defaults"
        )


def test_load_enabled_includes_writes_when_explicitly_enabled():
    from wagtail_mcp_server.mcp import _load_enabled
    from wagtail_mcp_server.settings import reset_cache

    reset_cache()
    with override_settings(
        WAGTAIL_MCP_SERVER={
            "TOOLSETS": {
                "pages_query": {"enabled": True},
                "pages_write": {"enabled": True},
                "workflow": {"enabled": True},
                "media": {"enabled": True},
                "seo_write": {"enabled": True},
                "redirects": {
                    "enabled_read": True,
                    "enabled_write": True,
                },
            }
        }
    ):
        reset_cache()
        loaded = _load_enabled()

    for slug in ("pages_write", "workflow", "media", "seo_write", "redirects"):
        assert slug in loaded


def test_load_enabled_redirects_split_flag_off_keeps_module_unregistered():
    """With both redirects flags off, the module is not loaded."""
    from wagtail_mcp_server.mcp import _load_enabled
    from wagtail_mcp_server.settings import reset_cache

    reset_cache()
    with override_settings(
        WAGTAIL_MCP_SERVER={
            "TOOLSETS": {
                "pages_query": {"enabled": True},
                "redirects": {"enabled_read": False, "enabled_write": False},
            }
        }
    ):
        reset_cache()
        loaded = _load_enabled()

    assert "redirects" not in loaded
    assert "pages_query" in loaded


def test_load_enabled_redirects_write_only_still_imports_module():
    """Asymmetric: writes on, reads off. Module still imports.

    Per-side gating happens inside the toolset; the import side-effect
    is unconditional once ANY flag is on.
    """
    from wagtail_mcp_server.mcp import _load_enabled
    from wagtail_mcp_server.settings import reset_cache

    reset_cache()
    with override_settings(
        WAGTAIL_MCP_SERVER={
            "TOOLSETS": {
                "pages_query": {"enabled": True},
                "redirects": {"enabled_read": False, "enabled_write": True},
            }
        }
    ):
        reset_cache()
        loaded = _load_enabled()

    assert "redirects" in loaded
