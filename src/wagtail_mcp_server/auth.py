"""Authentication backends for wagtail-mcp-server.

Two backends ship with the package:

``UserTokenAuth`` (default)
    One ``UserMcpToken`` per (agent, user) pair. The token resolves to a
    specific Django user; the tool call runs as that user and Wagtail
    permissions apply. Recommended for production. Supports revocation and
    per-agent labelling.

``BearerTokenAuth`` (dev only)
    Shared bearer token tied to a single service user. Demoted to dev use
    because there is no way to distinguish one caller from another. Kept
    so local scripts can hit the server without seeding a user row.

Both backends read the token from ``Authorization: Bearer <token>`` on HTTP
requests and from the ``WAGTAIL_MCP_SERVER_TOKEN`` environment variable on
stdio transports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser

from .settings import get_config


class AuthenticationFailed(Exception):
    """Raised when a token cannot be resolved to a Django user."""


@dataclass(slots=True)
class AuthResult:
    """Result of a successful token resolution."""

    user: AbstractBaseUser
    token_id: int | None
    label: str | None


def _read_http_token(headers: dict[str, str]) -> str | None:
    """Pull the token out of an HTTP Authorization header."""
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip() or None


def _read_stdio_token() -> str | None:
    return os.environ.get("WAGTAIL_MCP_SERVER_TOKEN") or None


class UserTokenAuth:
    """Resolve a bearer token to a ``UserMcpToken`` row."""

    def authenticate(
        self,
        *,
        http_headers: dict[str, str] | None = None,
    ) -> AuthResult:
        token = (
            _read_http_token(http_headers) if http_headers is not None else _read_stdio_token()
        )
        if not token:
            raise AuthenticationFailed("Missing token")

        # Import here so Django app registry is ready.
        from .models import UserMcpToken  # noqa: PLC0415

        try:
            row = UserMcpToken.objects.select_related("user").get(
                token_hash=UserMcpToken.hash_token(token), revoked_at__isnull=True
            )
        except UserMcpToken.DoesNotExist as exc:
            raise AuthenticationFailed("Invalid or revoked token") from exc

        if not row.user.is_active:
            raise AuthenticationFailed("User is inactive")

        row.mark_used()
        return AuthResult(user=row.user, token_id=row.pk, label=row.label)


class BearerTokenAuth:
    """Dev-only single-token backend. Discouraged for production."""

    def authenticate(
        self,
        *,
        http_headers: dict[str, str] | None = None,
    ) -> AuthResult:
        token = (
            _read_http_token(http_headers) if http_headers is not None else _read_stdio_token()
        )
        expected = os.environ.get("WAGTAIL_MCP_SERVER_DEV_TOKEN")
        if not (token and expected and token == expected):
            raise AuthenticationFailed("Invalid dev bearer token")

        User = get_user_model()
        username = os.environ.get("WAGTAIL_MCP_SERVER_DEV_USER", "mcp-dev")
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_active": True},
        )
        return AuthResult(user=user, token_id=None, label="dev-bearer")


def get_backend():
    """Resolve the configured auth backend class."""
    cfg = get_config()
    name = cfg["AUTH"]["BACKEND"]
    if name == "UserTokenAuth":
        return UserTokenAuth()
    if name == "BearerTokenAuth":
        return BearerTokenAuth()
    raise RuntimeError(f"Unknown auth backend: {name}")


# ---------------------------------------------------------------------------
# DRF adapter
# ---------------------------------------------------------------------------
#
# django-mcp-server consumes ``DJANGO_MCP_AUTHENTICATION_CLASSES`` as a list
# of dotted paths to ``rest_framework.authentication.BaseAuthentication``
# subclasses. The library's own backends (``UserTokenAuth`` /
# ``BearerTokenAuth``) use a different contract -- ``authenticate(http_headers=...)``
# returning ``AuthResult`` -- so we need a thin adapter that satisfies DRF's
# ``authenticate(self, request)`` signature and delegates to the configured
# backend underneath. This keeps the library's own backend API reusable by
# non-DRF consumers while still slotting cleanly into the MCP HTTP view.


class UserTokenDRFAuth:
    """DRF-style auth class that delegates to the configured backend.

    Returns ``(user, auth_result)`` on success so DRF sets
    ``request.user`` before the MCP dispatcher captures the request into
    the ``django_request_ctx`` ContextVar. The resolved
    :class:`AuthResult` is returned as the ``auth`` slot so callers that
    want the token id or label can read ``request.auth.token_id`` /
    ``request.auth.label``.

    Returning ``None`` (rather than raising) when the header is missing
    lets DRF fall through to any additional auth classes the host has
    configured; raising :class:`rest_framework.exceptions.AuthenticationFailed`
    forces a 401 immediately with a WWW-Authenticate header. We raise
    only when a token **is** presented but cannot be resolved.
    """

    www_authenticate_realm = "wagtail-mcp-server"

    def authenticate(self, request):
        # Deferred import so the app registry is up before we touch models.
        from rest_framework.exceptions import AuthenticationFailed as DRFAuthFailed

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return None  # let DRF try other auth classes or anonymous

        backend = get_backend()
        headers = {"Authorization": auth_header}
        try:
            result = backend.authenticate(http_headers=headers)
        except AuthenticationFailed as exc:
            # DRF expects its own exception to trigger the 401 path.
            raise DRFAuthFailed(str(exc)) from exc
        return (result.user, result)

    def authenticate_header(self, request):  # noqa: ARG002 - DRF contract
        return f'Bearer realm="{self.www_authenticate_realm}"'
