"""``manage.py mcp_serve``: start the MCP transport.

Two modes:

    --stdio           Read/write MCP frames on stdin/stdout. Used by
                      Claude Desktop, Cursor, and similar local clients.
    --http            Run the HTTP+SSE transport on the given host/port.

v0.1 scaffold: prints a usage stub and exits. Full wiring through
django-mcp-server lands in v0.2.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the wagtail-mcp-server transport (stdio or HTTP+SSE)."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--stdio", action="store_true")
        mode.add_argument("--http", action="store_true")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", default=8765, type=int)

    def handle(self, *args, **options):
        if options["stdio"]:
            self.stdout.write(
                "wagtail-mcp-server stdio transport is scaffolded. "
                "Full wiring lands in v0.2."
            )
        else:
            self.stdout.write(
                f"wagtail-mcp-server HTTP+SSE transport is scaffolded. "
                f"Would bind to {options['host']}:{options['port']}. "
                f"Full wiring lands in v0.2."
            )
