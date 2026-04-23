"""``wagtail-mcp-serve``: the standalone runtime entrypoint.

This is the script registered under ``[project.scripts]``. It does the
zero-config bootstrap:

    1. Picks ``DJANGO_SETTINGS_MODULE`` (defaults to the bundled
       :mod:`wagtail_mcp_server.standalone.settings`; honours an existing
       env var if set, so a user with a real Django project can still
       use this entrypoint as a pure dispatcher).
    2. Optionally points the bundled settings at a different data dir
       via ``WMS_DATA_DIR`` (set from ``--data-dir`` before Django
       boots, so the settings module sees the override).
    3. Calls :func:`django.setup`.
    4. Runs ``migrate --run-syncdb`` unless ``--no-migrate`` is given.
    5. On first boot (no existing tokens), creates a superuser named
       ``admin`` and mints an MCP token. Both are printed to stderr
       once and never again.
    6. Dispatches into the ``mcp_serve`` management command for the
       chosen transport.

Why ``stderr`` for the bootstrap printouts? Because ``--stdio`` has the
MCP transport bound to stdout; anything we print to stdout would be
parsed as an MCP frame and crash the client. ``stderr`` is safe and is
where local-CLI clients look for human-readable boot logs.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from typing import Any

DEFAULT_SETTINGS_MODULE = "wagtail_mcp_server.standalone.settings"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Build the CLI parser.

    Kept in its own function so tests can drive it without spawning a
    subprocess.
    """
    p = argparse.ArgumentParser(
        prog="wagtail-mcp-serve",
        description=(
            "Run a self-contained wagtail-mcp-server. No host Django "
            "project required: the bundled settings module ships SQLite "
            "and a sticky SECRET_KEY under ~/.local/share/wagtail-mcp-server "
            "(or the platform equivalent)."
        ),
    )
    transport = p.add_mutually_exclusive_group()
    transport.add_argument(
        "--stdio",
        dest="transport",
        action="store_const",
        const="stdio",
        help="Run over stdio (default if no transport given).",
    )
    transport.add_argument(
        "--http",
        dest="transport",
        action="store_const",
        const="http",
        help="Run over HTTP+SSE.",
    )
    p.set_defaults(transport="stdio")

    p.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    p.add_argument("--port", default=8765, type=int, help="HTTP bind port.")
    p.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Override the data directory (db.sqlite3, secret_key, media). "
            "Equivalent to setting WMS_DATA_DIR before launch."
        ),
    )
    p.add_argument(
        "--settings",
        default=None,
        help=(
            "Use a custom Django settings module instead of the bundled one. "
            "Equivalent to setting DJANGO_SETTINGS_MODULE before launch."
        ),
    )
    p.add_argument(
        "--no-migrate",
        action="store_true",
        help="Skip the auto-migrate step on boot.",
    )
    p.add_argument(
        "--no-bootstrap",
        action="store_true",
        help=(
            "Skip the first-boot superuser+token bootstrap. Useful for "
            "containers where credentials are seeded out-of-band."
        ),
    )
    p.add_argument(
        "--bootstrap-username",
        default="admin",
        help="Username to create on first boot. Default: admin.",
    )
    return p.parse_args(argv)


def _configure_environment(args: argparse.Namespace) -> str:
    """Pin ``DJANGO_SETTINGS_MODULE`` and ``WMS_DATA_DIR`` from CLI flags.

    Returns the settings module that will end up active. Idempotent:
    re-running with the same args is safe.
    """
    if args.data_dir:
        # Set before Django imports so the bundled settings module sees it.
        os.environ["WMS_DATA_DIR"] = args.data_dir

    if args.settings:
        settings_module = args.settings
    else:
        settings_module = os.environ.get(
            "DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE
        )
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    return settings_module


def _bootstrap_credentials(username: str) -> None:
    """Idempotent first-boot superuser + token mint.

    If any ``UserMcpToken`` row exists, this is a no-op -- prior runs
    have already provisioned credentials. Otherwise we make a superuser
    (if one with the requested username doesn't exist), assign it a
    random throwaway password, and mint a fresh token. Both are printed
    once to stderr.

    The throwaway password is intentional: standalone deployments are
    expected to authenticate via the MCP token, not the Django admin
    UI. An operator who actually wants admin login should call
    ``manage.py changepassword`` themselves.
    """
    from django.contrib.auth import get_user_model

    from wagtail_mcp_server.models import UserMcpToken

    if UserMcpToken.objects.exists():
        return

    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"is_staff": True, "is_superuser": True},
    )
    if created:
        user.set_password(secrets.token_urlsafe(32))
        user.is_staff = True
        user.is_superuser = True
        user.save()

    _row, plaintext = UserMcpToken.issue(user=user, label="standalone bootstrap")

    print(  # noqa: T201 - intentional bootstrap log
        "wagtail-mcp-serve: first-boot bootstrap complete.\n"
        f"  Superuser: {username}  (random password set; use "
        f"`manage.py changepassword {username}` if you need to log in)\n"
        f"  MCP token: {plaintext}\n"
        "  Save the token now -- it will not be shown again.",
        file=sys.stderr,
        flush=True,
    )


def _run_migrate() -> None:
    from django.core.management import call_command

    # ``--run-syncdb`` covers the contenttypes/auth tables for apps
    # without explicit migrations on a brand-new SQLite file.
    call_command("migrate", "--run-syncdb", verbosity=0)


def _dispatch_serve(transport: str, host: str, port: int) -> None:
    from django.core.management import call_command

    if transport == "stdio":
        call_command("mcp_serve", "--stdio")
    else:
        call_command("mcp_serve", "--http", f"--host={host}", f"--port={port}")


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for ``wagtail-mcp-serve``.

    Returns an exit code so the test suite can call this directly
    instead of always shelling out.
    """
    args = _parse_args(argv)
    _configure_environment(args)

    import django

    django.setup()

    if not args.no_migrate:
        _run_migrate()

    if not args.no_bootstrap:
        try:
            _bootstrap_credentials(args.bootstrap_username)
        except Exception as exc:  # noqa: BLE001 - bootstrap failures shouldn't kill serve
            print(
                f"wagtail-mcp-serve: bootstrap step skipped ({exc!r}). "
                "Continuing with serve.",
                file=sys.stderr,
                flush=True,
            )

    _dispatch_serve(args.transport, args.host, args.port)
    return 0


def _cli_entry() -> Any:
    """Console-script wrapper. ``[project.scripts]`` points here."""
    sys.exit(main())


if __name__ == "__main__":
    _cli_entry()
