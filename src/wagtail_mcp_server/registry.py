"""Toolset registration for wagtail-mcp-server.

Called once from ``AppConfig.ready``. Walks the ``TOOLSETS`` config and
registers each enabled toolset with django-mcp-server. Unknown toolset
names are rejected by settings validation, so this module never sees a
name it cannot dispatch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module

from .settings import get_config

logger = logging.getLogger(__name__)

# Map config key -> (module, class attribute) for each toolset.
TOOLSET_MAP: dict[str, tuple[str, str]] = {
    "pages_query": ("wagtail_mcp_server.toolsets.pages_query", "PageQueryToolset"),
    "pages_write": ("wagtail_mcp_server.toolsets.pages_write", "PageWriteToolset"),
    "workflow": ("wagtail_mcp_server.toolsets.workflow", "WorkflowToolset"),
    "media": ("wagtail_mcp_server.toolsets.media", "MediaToolset"),
    "seo_query": ("wagtail_mcp_server.toolsets.seo_query", "SEOQueryToolset"),
    "seo_write": ("wagtail_mcp_server.toolsets.seo_write", "SEOWriteToolset"),
}


def _load_class(module_path: str, class_name: str) -> Callable:
    module = import_module(module_path)
    return getattr(module, class_name)


def register_enabled_toolsets() -> None:
    """Register every enabled toolset with the MCP dispatcher.

    v0.1 scaffold: this walks the config but the actual
    ``django_mcp_server`` registration is a TODO that lands alongside
    real tool implementations. For now the function is a safe no-op so
    importing the app never crashes.
    """
    cfg = get_config()
    for name, toolset_cfg in cfg["TOOLSETS"].items():
        if not toolset_cfg.get("enabled", False):
            continue
        module_path, class_name = TOOLSET_MAP[name]
        try:
            _load_class(module_path, class_name)
        except (ImportError, AttributeError):
            logger.warning(
                "wagtail_mcp_server: toolset '%s' is enabled in config but its "
                "implementation class %s.%s is not importable yet.",
                name,
                module_path,
                class_name,
            )
            continue
        logger.info("wagtail_mcp_server: registered toolset '%s' (scaffold)", name)
