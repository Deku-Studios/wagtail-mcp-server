"""CLI wrapper for wagtail-mcp-server.

Dispatches to the equivalent ``manage.py`` commands so operators can run
common operations (serve, introspect, issue/revoke tokens) without hunting
for the Django project's ``manage.py``.

Usage:

    wagtail-mcp-server serve --stdio
    wagtail-mcp-server serve --http --port 8765
    wagtail-mcp-server introspect
    wagtail-mcp-server issue-token --user lex --label "Lex Nanobot"
    wagtail-mcp-server revoke-token <token-id-or-prefix>
"""

from __future__ import annotations

import os
import sys

import click

DJANGO_SETTINGS_HINT = (
    "Set DJANGO_SETTINGS_MODULE to the host project's settings module, "
    "e.g. 'yourproject.settings'."
)


def _ensure_django() -> None:
    """Bootstrap Django before any DB-touching command runs."""
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        click.echo(f"ERROR: DJANGO_SETTINGS_MODULE is not set. {DJANGO_SETTINGS_HINT}", err=True)
        sys.exit(2)
    import django  # noqa: PLC0415

    django.setup()


@click.group(
    help="Run and operate a wagtail-mcp-server instance.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(package_name="wagtail-mcp-server")
def main() -> None:
    """Thin dispatcher; each subcommand does the work."""


@main.command("serve")
@click.option("--stdio", "transport", flag_value="stdio", help="Run over stdio.")
@click.option("--http", "transport", flag_value="http", help="Run over HTTP+SSE.")
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--host", default="127.0.0.1", show_default=True)
def serve(transport: str | None, port: int, host: str) -> None:
    """Start the MCP server over the chosen transport."""
    _ensure_django()
    from django.core.management import call_command  # noqa: PLC0415

    if transport is None:
        transport = "stdio"

    if transport == "stdio":
        call_command("mcp_serve", "--stdio")
    else:
        call_command("mcp_serve", "--http", f"--host={host}", f"--port={port}")


@main.command("introspect")
def introspect() -> None:
    """List enabled toolsets, their tools, and JSON schemas."""
    _ensure_django()
    from django.core.management import call_command  # noqa: PLC0415

    call_command("mcp_introspect")


@main.command("issue-token")
@click.option("--user", required=True, help="Django username (must already exist).")
@click.option("--label", required=True, help="Human-readable label, e.g. agent name.")
def issue_token(user: str, label: str) -> None:
    """Mint a fresh per-user MCP token. The token is printed once to stdout."""
    _ensure_django()
    from django.core.management import call_command  # noqa: PLC0415

    call_command("mcp_issue_token", f"--user={user}", f"--label={label}")


@main.command("revoke-token")
@click.argument("token_id")
def revoke_token(token_id: str) -> None:
    """Revoke a token by its integer id or short prefix."""
    _ensure_django()
    from django.core.management import call_command  # noqa: PLC0415

    call_command("mcp_revoke_token", token_id)


if __name__ == "__main__":
    main()
