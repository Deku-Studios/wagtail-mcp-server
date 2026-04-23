"""django-mcp-server autodiscover entry point.

django-mcp-server's ``McpServerConfig.ready()`` calls
``autodiscover_modules('mcp')`` at Django startup, which imports
``wagtail_mcp_server.mcp`` in every Django process. Importing a toolset
class has a side-effect: ``ToolsetMeta`` (the base metaclass on
:class:`mcp_server.djangomcp.MCPToolset`) adds it to a process-wide
registry at class-creation time. That same ``ready()`` then iterates the
registry and publishes every class as an MCP server tool.

We therefore use **conditional imports** here to honour the host's
``WAGTAIL_MCP_SERVER.TOOLSETS`` config. A toolset is only imported --
and therefore only registered -- when its ``enabled`` flag is true. This
is the only supported gating path; merely not enabling a toolset while
still importing the module would leak all its tools onto the MCP wire.

Adding a new toolset
====================

1. Implement the toolset class in ``wagtail_mcp_server/toolsets/<name>.py``
   with a ``class FooToolset(MCPToolset):`` declaration.
2. Add a mapping to :data:`_IMPORTS` below keyed by the config slug.
3. Add the default config under ``DEFAULT_CONFIG["TOOLSETS"]`` in
   :mod:`wagtail_mcp_server.settings`.

That's the full wiring; the metaclass does the rest.
"""

from __future__ import annotations

import logging
from importlib import import_module

from .settings import get_config, toolset_enabled

logger = logging.getLogger(__name__)


# Slug (as it appears under WAGTAIL_MCP_SERVER.TOOLSETS) -> importable
# module path. We import the module (not the class) because the
# side-effect we want -- metaclass registration -- fires at module load
# time. The class name is captured only for the log line so operators
# can see which toolsets went live.
_IMPORTS: dict[str, tuple[str, str]] = {
    "pages_query": ("wagtail_mcp_server.toolsets.pages_query", "PageQueryToolset"),
    "pages_write": ("wagtail_mcp_server.toolsets.pages_write", "PageWriteToolset"),
    "workflow": ("wagtail_mcp_server.toolsets.workflow", "WorkflowToolset"),
    "media": ("wagtail_mcp_server.toolsets.media", "MediaToolset"),
    "seo_query": ("wagtail_mcp_server.toolsets.seo_query", "SEOQueryToolset"),
    "seo_write": ("wagtail_mcp_server.toolsets.seo_write", "SEOWriteToolset"),
    # New in v0.5: read-only surface for Wagtail Collections. On by default;
    # safe (no bytes, no mutation, no cross-tenant data).
    "collections_query": (
        "wagtail_mcp_server.toolsets.collections_query",
        "CollectionsQueryToolset",
    ),
    # New in v0.5: read-only enumeration of registered snippets. On by
    # default; per-type dispatch still requires Django view perm.
    "snippets_query": (
        "wagtail_mcp_server.toolsets.snippets_query",
        "SnippetsQueryToolset",
    ),
    # New in v0.5. The ``redirects`` toolset is the only one using the
    # split enabled_read/enabled_write shape -- reads on by default,
    # writes off by default. Per-tool gating lives inside the toolset
    # (see :func:`settings.toolset_write_enabled`).
    "redirects": (
        "wagtail_mcp_server.toolsets.redirects",
        "RedirectsToolset",
    ),
}


def _load_enabled() -> list[str]:
    """Import every enabled toolset module; return the list of slugs loaded.

    Errors are logged and swallowed per toolset so a single broken module
    cannot take down the whole MCP surface. Import failures at this point
    are almost always a missing optional dependency (e.g. the media
    toolset needing ``wagtail.images`` and ``wagtail.documents``).
    """
    # ``get_config`` is called for its validation side-effect; the per-slug
    # enable check goes through :func:`toolset_enabled`, which handles both
    # the legacy single ``enabled`` flag and the split-flag shape used by
    # ``redirects`` (``enabled_read`` / ``enabled_write``). Either flag on
    # triggers import; per-tool gating is the toolset's own responsibility.
    get_config()
    loaded: list[str] = []
    for slug, (module_path, class_name) in _IMPORTS.items():
        if not toolset_enabled(slug):
            continue
        try:
            import_module(module_path)
        except Exception:  # noqa: BLE001 - log + continue so one bad toolset can't break the rest
            logger.exception(
                "wagtail_mcp_server: failed to load toolset '%s' (%s.%s); skipping.",
                slug,
                module_path,
                class_name,
            )
            continue
        loaded.append(slug)
        logger.info(
            "wagtail_mcp_server: registered toolset '%s' (%s)", slug, class_name
        )
    return loaded


# Run at import time. django-mcp-server's autodiscover fires this during
# its own ``ready()``, which runs after every Django app's ``ready()``;
# by that point ``get_config()`` has been validated and app registries
# are populated, so it is safe to import toolset modules whose top-level
# code touches Wagtail.
_LOADED_TOOLSETS: list[str] = _load_enabled()
