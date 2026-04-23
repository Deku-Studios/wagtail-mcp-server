"""Settings resolver for wagtail-mcp-server.

All configuration lives under a single ``WAGTAIL_MCP_SERVER`` dict in the host
project's Django settings. This module supplies defaults, validates the shape,
and exposes a single ``get_config()`` helper the rest of the package uses.

Design goals:
    - One namespace, one dict. Nothing leaks into the Django settings top
      level except the dict itself.
    - Safe defaults: every write toolset is off, destructive ops are off,
      impersonation is off. OTel emission is on by default as of v0.5:
      it is a no-op on hosts that have not configured an OpenTelemetry
      SDK, so the default costs nothing but unlocks observability for
      hosts that do.
    - Resolved once at startup. Mutating the settings dict at runtime is not
      supported.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Canonical defaults. Any new config key must have an entry here.
DEFAULTS: dict[str, Any] = {
    "AUTH": {
        "BACKEND": "UserTokenAuth",
        "ALLOW_IMPERSONATION": False,
    },
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query": {"enabled": True},
        # New in v0.5. Read-only; safe to ship on by default.
        "collections_query": {"enabled": True},
        "snippets_query": {"enabled": True},
        "pages_write": {"enabled": False},
        "workflow": {"enabled": False},
        "media": {"enabled": False},
        "seo_write": {"enabled": False},
        # New in v0.5. ``redirects`` is the only toolset that splits
        # read and write onto separate flags: many operators want to let
        # agents *see* existing redirects without also granting them the
        # ability to mint new ones. Reads on by default, writes off.
        "redirects": {"enabled_read": True, "enabled_write": False},
    },
    "LIMITS": {
        "MAX_PAGE_SIZE": 50,
        "MAX_SEARCH_RESULTS": 100,
        "MAX_UPLOAD_MB": 25,
        "ALLOW_DESTRUCTIVE": False,
    },
    "RICHTEXT_FORMAT": "html",  # or "draftail"
    "WRITE_VALIDATION": "strict",  # or "permissive"
    "AUDIT": {
        "ENABLED": True,
        "RETENTION_DAYS": 90,
        # On by default as of v0.5. No-op when the host process has not
        # configured an OpenTelemetry SDK, so the default is safe for
        # every install. Set to False explicitly to suppress.
        "EMIT_OTEL": True,
    },
}

_KNOWN_AUTH_BACKENDS = {"UserTokenAuth", "BearerTokenAuth"}
_KNOWN_RICHTEXT_FORMATS = {"html", "draftail"}
_KNOWN_WRITE_VALIDATION = {"strict", "permissive"}

# All known toolset keys. Unknown keys in user config raise.
_KNOWN_TOOLSETS = set(DEFAULTS["TOOLSETS"].keys())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Shallow-first deep merge. ``override`` wins on scalar collisions."""
    out = deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _validate(config: dict[str, Any]) -> None:
    backend = config["AUTH"]["BACKEND"]
    if backend not in _KNOWN_AUTH_BACKENDS:
        raise ImproperlyConfigured(
            f"WAGTAIL_MCP_SERVER.AUTH.BACKEND='{backend}' is not a known backend. "
            f"Expected one of {sorted(_KNOWN_AUTH_BACKENDS)}."
        )

    richtext = config["RICHTEXT_FORMAT"]
    if richtext not in _KNOWN_RICHTEXT_FORMATS:
        raise ImproperlyConfigured(
            f"WAGTAIL_MCP_SERVER.RICHTEXT_FORMAT='{richtext}' is invalid. "
            f"Expected one of {sorted(_KNOWN_RICHTEXT_FORMATS)}."
        )

    wv = config["WRITE_VALIDATION"]
    if wv not in _KNOWN_WRITE_VALIDATION:
        raise ImproperlyConfigured(
            f"WAGTAIL_MCP_SERVER.WRITE_VALIDATION='{wv}' is invalid. "
            f"Expected one of {sorted(_KNOWN_WRITE_VALIDATION)}."
        )

    unknown = set(config["TOOLSETS"].keys()) - _KNOWN_TOOLSETS
    if unknown:
        raise ImproperlyConfigured(
            f"WAGTAIL_MCP_SERVER.TOOLSETS contains unknown keys: {sorted(unknown)}. "
            f"Known toolsets: {sorted(_KNOWN_TOOLSETS)}."
        )


_cached: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Return the resolved, validated WAGTAIL_MCP_SERVER config dict.

    Cached after the first call. Changes to Django settings after process
    start are not reflected; restart the process to pick them up.
    """
    global _cached
    if _cached is not None:
        return _cached
    user_override = getattr(settings, "WAGTAIL_MCP_SERVER", {}) or {}
    merged = _deep_merge(DEFAULTS, user_override)
    _validate(merged)
    _cached = merged
    return _cached


def reset_cache() -> None:
    """Clear the cached config. Intended for tests only."""
    global _cached
    _cached = None


def toolset_enabled(name: str) -> bool:
    """True iff toolset ``name`` is enabled for at least one of read or write.

    Treats the split-flag shape (``enabled_read`` / ``enabled_write``,
    currently only ``redirects``) and the single-flag shape uniformly:
    the toolset is "enabled" for registration purposes if *any* of its
    flags is on, because ``mcp.py`` only needs to decide whether to
    import the module. Per-tool gating is handled inside the toolset.
    """
    cfg = get_config()
    entry = cfg["TOOLSETS"].get(name, {})
    if "enabled" in entry:
        return bool(entry["enabled"])
    return bool(entry.get("enabled_read") or entry.get("enabled_write"))


def toolset_read_enabled(name: str) -> bool:
    """True iff read-side tools of toolset ``name`` should dispatch.

    For single-flag toolsets this mirrors :func:`toolset_enabled`; for
    the split-flag ``redirects`` toolset it isolates reads from writes.
    """
    cfg = get_config()
    entry = cfg["TOOLSETS"].get(name, {})
    if "enabled_read" in entry:
        return bool(entry["enabled_read"])
    return bool(entry.get("enabled", False))


def toolset_write_enabled(name: str) -> bool:
    """True iff write-side tools of toolset ``name`` should dispatch.

    For single-flag toolsets this mirrors :func:`toolset_enabled`; for
    the split-flag ``redirects`` toolset it gates mutating tools
    independently of read-side ones.
    """
    cfg = get_config()
    entry = cfg["TOOLSETS"].get(name, {})
    if "enabled_write" in entry:
        return bool(entry["enabled_write"])
    return bool(entry.get("enabled", False))
