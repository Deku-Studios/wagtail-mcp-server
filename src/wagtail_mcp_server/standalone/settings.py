"""Bundled Django settings for the standalone ``wagtail-mcp-serve`` runtime.

These are the settings ``wagtail_mcp_server.standalone.serve.main`` points
``DJANGO_SETTINGS_MODULE`` at when no host project is provided. They are
deliberately minimal: SQLite, the smallest set of Wagtail apps that lets
the toolsets import, and a sticky ``SECRET_KEY`` so subsequent boots do
not invalidate sessions.

Storage layout
==============

All on-disk state lives under ``WMS_DATA_DIR`` (default:
``$XDG_DATA_HOME/wagtail-mcp-server`` on Linux, ``~/Library/Application
Support/wagtail-mcp-server`` on macOS, ``%LOCALAPPDATA%\\wagtail-mcp-server``
on Windows, falling back to ``~/.wagtail-mcp-server``)::

    <data dir>/
        db.sqlite3        the Wagtail database
        secret_key        regenerated only if missing
        media/            user-uploaded images, documents
        static/           collected static (only on --collect)

Override at boot with ``--data-dir /some/path`` or ``WMS_DATA_DIR=...``.

Safety defaults
===============

The standalone runtime is meant for "tinker on my laptop" use. Every
write toolset ships **off** here just like in the library defaults; the
operator must opt in explicitly. Read-only toolsets (``pages_query``,
``seo_query``, ``collections_query``, ``snippets_query``, the read side
of ``redirects``) are on so a freshly installed server has something
useful to expose immediately.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    """Pick a sensible per-OS data dir.

    Honours ``XDG_DATA_HOME`` on Linux. macOS uses ``~/Library/Application
    Support`` to match Apple's HIG. Windows uses ``LOCALAPPDATA`` if set.
    Everything else falls back to ``~/.wagtail-mcp-server``.
    """
    explicit = os.environ.get("WMS_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "wagtail-mcp-server"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "wagtail-mcp-server"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "wagtail-mcp-server"
    return Path.home() / ".local" / "share" / "wagtail-mcp-server"


DATA_DIR: Path = _default_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_or_create_secret_key() -> str:
    """Persist a 64-char SECRET_KEY in ``DATA_DIR/secret_key``.

    Created on first boot with mode 0600 so other local users can't read
    it. Subsequent boots reuse the same key, keeping any existing
    sessions and signed values valid.
    """
    key_path = DATA_DIR / "secret_key"
    if key_path.exists():
        return key_path.read_text().strip()
    key = secrets.token_urlsafe(48)
    key_path.write_text(key)
    # chmod is best-effort: Windows POSIX-perm support is partial and
    # the file is already on disk regardless. Suppress narrowly.
    with contextlib.suppress(OSError):
        key_path.chmod(0o600)
    return key


SECRET_KEY: str = _load_or_create_secret_key()
DEBUG = False
ALLOWED_HOSTS = ["*"]
USE_TZ = True
TIME_ZONE = "UTC"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DATA_DIR / "db.sqlite3"),
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Wagtail core (smallest set that lets the toolsets import cleanly).
    "taggit",
    "wagtail.admin",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.search",
    "wagtail.embeds",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail",
    # Library under the runtime.
    "wagtail_mcp_server",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# Standalone deployments don't need URL routing for the MCP surface --
# stdio + SSE bypass it -- but Django insists on a urlconf. An empty
# urls module is enough.
ROOT_URLCONF = "wagtail_mcp_server.standalone.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

STATIC_URL = "/static/"
STATIC_ROOT = str(DATA_DIR / "static")
MEDIA_URL = "/media/"
MEDIA_ROOT = str(DATA_DIR / "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
WAGTAIL_SITE_NAME = "wagtail-mcp-server (standalone)"

# Read toolsets on, write toolsets off. The library's settings resolver
# deep-merges this with its own defaults, so this dict only needs to
# state the *deltas* from the resolver's baseline -- but we restate the
# read flags explicitly so an operator scanning this file can see what's
# enabled out of the box without cross-referencing
# :mod:`wagtail_mcp_server.settings`.
WAGTAIL_MCP_SERVER: dict = {
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query": {"enabled": True},
        "collections_query": {"enabled": True},
        "snippets_query": {"enabled": True},
        "redirects": {"enabled_read": True, "enabled_write": False},
    },
    # Audit on, OTel off in standalone (no collector to point at).
    "AUDIT": {"ENABLED": True, "EMIT_OTEL": False},
}


def _user_overrides() -> None:
    """Merge ``WMS_OVERRIDE_*`` env vars into ``WAGTAIL_MCP_SERVER``.

    Tiny escape hatch so an operator can flip a single flag without
    forking this settings module. Recognised forms (case-insensitive
    booleans only, since this is meant for quick-toggling)::

        WMS_OVERRIDE_PAGES_WRITE=1     # enable pages_write
        WMS_OVERRIDE_REDIRECTS_WRITE=1 # enable redirects.enabled_write
        WMS_OVERRIDE_ALLOW_DESTRUCTIVE=1
        WMS_OVERRIDE_ALLOW_IMPERSONATION=1

    Anything more elaborate (custom RICHTEXT_FORMAT, retention, etc.)
    requires the user to write their own settings module and point
    ``DJANGO_SETTINGS_MODULE`` at it.
    """
    truthy = {"1", "true", "yes", "on"}

    def _on(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in truthy

    cfg = WAGTAIL_MCP_SERVER
    cfg.setdefault("TOOLSETS", {})
    cfg.setdefault("LIMITS", {})
    cfg.setdefault("AUTH", {})

    # Toolset write flags.
    for slug in ("pages_write", "workflow", "media", "seo_write"):
        if _on(f"WMS_OVERRIDE_{slug.upper()}"):
            cfg["TOOLSETS"].setdefault(slug, {})["enabled"] = True
    if _on("WMS_OVERRIDE_REDIRECTS_WRITE"):
        cfg["TOOLSETS"].setdefault("redirects", {})["enabled_write"] = True

    if _on("WMS_OVERRIDE_ALLOW_DESTRUCTIVE"):
        cfg["LIMITS"]["ALLOW_DESTRUCTIVE"] = True
    if _on("WMS_OVERRIDE_ALLOW_IMPERSONATION"):
        cfg["AUTH"]["ALLOW_IMPERSONATION"] = True


_user_overrides()
