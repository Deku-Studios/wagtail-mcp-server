"""``manage.py mcp_issue_token``: mint a fresh per-user MCP token.

Example::

    python manage.py mcp_issue_token --user lex --label "Lex Nanobot"

The plaintext token is printed once to stdout. It is not persisted.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Issue a new per-user MCP token. The plaintext is printed once."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Django username (must exist).")
        parser.add_argument("--label", required=True, help="Human-readable label, e.g. agent name.")

    def handle(self, *args, **options):
        from wagtail_mcp_server.models import UserMcpToken  # noqa: PLC0415

        User = get_user_model()
        username = options["user"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"No user with username='{username}'. Create it first with createsuperuser "
                "or your own provisioning flow."
            ) from exc

        row, plaintext = UserMcpToken.issue(user=user, label=options["label"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Issued token id={row.pk} label='{row.label}' prefix={row.token_prefix}"
            )
        )
        self.stdout.write("")
        self.stdout.write("Plaintext (shown once; will not be retrievable again):")
        self.stdout.write(self.style.WARNING(plaintext))
