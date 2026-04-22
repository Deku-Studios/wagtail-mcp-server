"""Django app config for wagtail-mcp-server."""

from django.apps import AppConfig


class WagtailMCPServerConfig(AppConfig):
    """Wagtail MCP Server app config.

    Loads defaults, validates the ``WAGTAIL_MCP_SERVER`` settings dict,
    and hooks signals. Actual toolset registration is driven by
    django-mcp-server's ``autodiscover_modules('mcp')`` pass, which
    imports :mod:`wagtail_mcp_server.mcp` and triggers conditional
    loading of the enabled toolsets. See ``mcp.py`` for the full
    lifecycle.
    """

    name = "wagtail_mcp_server"
    verbose_name = "Wagtail MCP Server"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Kept lazy so importing this app in ``INSTALLED_APPS`` does not
        # force Wagtail to load before Django is ready. The ``signals``
        # module only wires post-save/etc hooks; it has no side-effect
        # on the MCP surface.
        from . import signals  # noqa: F401
        # Also validate + cache the config now so boot errors surface on
        # startup rather than on the first request.
        from .settings import get_config

        get_config()
