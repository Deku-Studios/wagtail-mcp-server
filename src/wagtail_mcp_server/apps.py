"""Django app config for wagtail-mcp-server."""

from django.apps import AppConfig


class WagtailMCPServerConfig(AppConfig):
    """Wagtail MCP Server app config.

    Loads defaults, validates the WAGTAIL_MCP_SERVER settings dict, and
    wires tool registration against django-mcp-server at startup.
    """

    name = "wagtail_mcp_server"
    verbose_name = "Wagtail MCP Server"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Import signals and register toolsets with django-mcp-server.
        # Kept lazy so importing this app in ``INSTALLED_APPS`` does not
        # force Wagtail to be loaded before Django is ready.
        from . import signals  # noqa: F401
        from .registry import register_enabled_toolsets

        register_enabled_toolsets()
