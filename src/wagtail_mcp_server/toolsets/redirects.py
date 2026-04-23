"""Redirects toolset (read on, write off by default).

New in v0.5. Wraps ``wagtail.contrib.redirects`` with two read tools and
three write tools:

    redirects.list      Paginated list of redirects (filter by site).
    redirects.get       One redirect by id.
    redirects.create    Create a redirect, pointing at a page or an
                        external URL.
    redirects.update    Update any mutable field of a redirect.
    redirects.delete    Delete a redirect (gated on LIMITS.ALLOW_DESTRUCTIVE).

Configuration
-------------
This is the only toolset in the package that uses the split-flag
shape::

    WAGTAIL_MCP_SERVER = {
        "TOOLSETS": {
            "redirects": {
                "enabled_read": True,   # default
                "enabled_write": False, # default
            },
        },
    }

Operators often want agents to be able to *read* the redirect table
(e.g. to verify a link rewrite before writing marketing copy) without
granting the ability to create or destroy redirects. The split flags
make that ergonomic without inventing two toolset slugs for what is
semantically one domain.

Per-tool gating lives inside this module rather than in ``mcp.py``:
``mcp.py`` imports the module whenever *either* flag is on (metaclass
registration is an all-or-nothing side-effect), and each write tool
checks the write flag before executing.

Permissions
-----------
Reads require authentication. Writes additionally require the
authenticating user to hold the standard
``wagtailredirects.add_redirect`` / ``change_redirect`` /
``delete_redirect`` Django permissions. Deletes *also* require
``LIMITS.ALLOW_DESTRUCTIVE`` -- three gates, same as pages.delete.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from mcp_server.djangomcp import MCPToolset

from ..settings import get_config, toolset_read_enabled, toolset_write_enabled

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100

# The slug redirects operators configure in WAGTAIL_MCP_SERVER.TOOLSETS.
_SLUG = "redirects"


class RedirectsToolset(MCPToolset):
    """django-mcp-server toolset for Wagtail redirects."""

    name = "redirects"
    version = "0.5.0"

    # =========================================================== reads

    def redirects_list(
        self,
        *,
        site_id: int | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """Paginated list of redirects, optionally scoped to one site."""
        _require_read_enabled()
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        Redirect = _redirect_model()
        qs = Redirect.objects.all().order_by("old_path")
        if site_id is not None:
            qs = qs.filter(site_id=site_id)
        return _paginate(qs, page, page_size, serializer=_serialize_redirect)

    def redirects_get(self, *, id: int) -> dict[str, Any] | None:
        """Fetch one redirect by id. Returns ``None`` if missing."""
        _require_read_enabled()
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        Redirect = _redirect_model()
        try:
            redirect = Redirect.objects.get(pk=id)
        except Redirect.DoesNotExist:
            return None
        return _serialize_redirect(redirect)

    # ========================================================== writes

    def redirects_create(
        self,
        *,
        old_path: str,
        redirect_page_id: int | None = None,
        redirect_link: str | None = None,
        site_id: int | None = None,
        is_permanent: bool = True,
    ) -> dict[str, Any]:
        """Create a new redirect. Exactly one of page id or link is required."""
        _require_write_enabled()
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_perm(user, "add")
        _require_single_target(redirect_page_id, redirect_link)

        Redirect = _redirect_model()
        kwargs: dict[str, Any] = {
            "old_path": _normalize_old_path(old_path),
            "is_permanent": bool(is_permanent),
            "site_id": site_id,
        }
        if redirect_page_id is not None:
            kwargs["redirect_page_id"] = int(redirect_page_id)
        if redirect_link is not None:
            kwargs["redirect_link"] = redirect_link

        redirect = Redirect.objects.create(**kwargs)
        return _serialize_redirect(redirect)

    def redirects_update(
        self,
        *,
        id: int,
        old_path: str | None = None,
        redirect_page_id: int | None = None,
        redirect_link: str | None = None,
        site_id: int | None = None,
        is_permanent: bool | None = None,
    ) -> dict[str, Any]:
        """Update a redirect's mutable fields. Only provided fields change."""
        _require_write_enabled()
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_perm(user, "change")

        Redirect = _redirect_model()
        try:
            redirect = Redirect.objects.get(pk=id)
        except Redirect.DoesNotExist as exc:
            raise ValueError(f"Redirect id={id} does not exist.") from exc

        if old_path is not None:
            redirect.old_path = _normalize_old_path(old_path)
        # Switching the target: accept either side, but if both arrive,
        # the page id wins and the text link is cleared.
        if redirect_page_id is not None:
            redirect.redirect_page_id = int(redirect_page_id)
            redirect.redirect_link = ""
        elif redirect_link is not None:
            redirect.redirect_link = redirect_link
            redirect.redirect_page = None
        if site_id is not None:
            # ``site_id=0`` is treated as "clear the site scope". Callers
            # who really want id=0 aren't a thing -- Wagtail sites start
            # at 1.
            redirect.site_id = site_id or None
        if is_permanent is not None:
            redirect.is_permanent = bool(is_permanent)

        redirect.save()
        return _serialize_redirect(redirect)

    def redirects_delete(self, *, id: int) -> dict[str, Any]:
        """Delete a redirect. Gated on ``LIMITS.ALLOW_DESTRUCTIVE``."""
        _require_write_enabled()
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_perm(user, "delete")
        _require_allow_destructive()

        Redirect = _redirect_model()
        try:
            redirect = Redirect.objects.get(pk=id)
        except Redirect.DoesNotExist as exc:
            raise ValueError(f"Redirect id={id} does not exist.") from exc
        payload = _serialize_redirect(redirect)
        redirect.delete()
        return {"deleted": True, "redirect": payload}


# ===================================================================== helpers


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Anonymous users cannot call redirects.* tools.")


def _require_read_enabled() -> None:
    if not toolset_read_enabled(_SLUG):
        raise PermissionDenied(
            "redirects read tools are disabled. Set "
            "WAGTAIL_MCP_SERVER.TOOLSETS.redirects.enabled_read=True to enable."
        )


def _require_write_enabled() -> None:
    if not toolset_write_enabled(_SLUG):
        raise PermissionDenied(
            "redirects write tools are disabled. Set "
            "WAGTAIL_MCP_SERVER.TOOLSETS.redirects.enabled_write=True to enable."
        )


def _require_perm(user: Any, action: str) -> None:
    """Require the standard Django ``<action>_redirect`` permission."""
    if getattr(user, "is_superuser", False):
        return
    codename = f"wagtailredirects.{action}_redirect"
    if not user.has_perm(codename):
        raise PermissionDenied(
            f"User lacks '{codename}' permission required for redirects.{action}."
        )


def _require_allow_destructive() -> None:
    cfg = get_config()
    if not cfg["LIMITS"].get("ALLOW_DESTRUCTIVE", False):
        raise PermissionDenied(
            "redirects.delete requires LIMITS.ALLOW_DESTRUCTIVE=True. "
            "Three gates are required: toolset enabled_write, Wagtail "
            "delete_redirect perm, and ALLOW_DESTRUCTIVE."
        )


def _require_single_target(page_id: int | None, link: str | None) -> None:
    if page_id is None and not link:
        raise ValueError(
            "redirects.create requires exactly one of redirect_page_id or "
            "redirect_link; both were empty."
        )
    if page_id is not None and link:
        raise ValueError(
            "redirects.create requires exactly one of redirect_page_id or "
            "redirect_link; both were provided."
        )


def _normalize_old_path(old_path: str) -> str:
    """Wagtail's Redirect model normalises old_path to lower + stripped.

    Applying the same normalisation up front ensures round-trips match
    what the admin UI does, so the agent never ends up with two redirects
    for ``/Foo`` and ``/foo`` that would otherwise collide at save.
    """
    return (old_path or "").lower().rstrip("/") or "/"


def _redirect_model() -> Any:
    from wagtail.contrib.redirects.models import Redirect

    return Redirect


def _serialize_redirect(redirect: Any) -> dict[str, Any]:
    return {
        "id": redirect.pk,
        "old_path": redirect.old_path,
        "redirect_page_id": redirect.redirect_page_id,
        "redirect_link": redirect.redirect_link or None,
        "site_id": redirect.site_id,
        "is_permanent": redirect.is_permanent,
        "automatically_created": redirect.automatically_created,
        "created": _iso(getattr(redirect, "created", None)),
    }


def _paginate(
    qs: Any, page: int, page_size: int | None, *, serializer: Any
) -> dict[str, Any]:
    cfg = get_config()
    default_page_size = int(cfg["LIMITS"].get("MAX_PAGE_SIZE", DEFAULT_LIST_LIMIT))
    size = int(page_size or default_page_size)
    if size <= 0:
        raise ValueError("page_size must be positive.")
    if page <= 0:
        raise ValueError("page must be positive.")
    size = min(size, MAX_LIST_LIMIT)
    offset = (page - 1) * size
    total = qs.count()
    rows = list(qs[offset : offset + size])
    return {
        "total": total,
        "page": page,
        "page_size": size,
        "results": [serializer(row) for row in rows],
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()
