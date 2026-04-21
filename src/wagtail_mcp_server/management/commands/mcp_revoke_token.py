"""``manage.py mcp_revoke_token``: revoke a token by id or prefix.

Examples::

    python manage.py mcp_revoke_token 42
    python manage.py mcp_revoke_token AbCdEfGh

Revocation is idempotent. Revoking an already-revoked token is a no-op
that exits zero.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Revoke a UserMcpToken by integer id or plaintext prefix."

    def add_arguments(self, parser):
        parser.add_argument("token_id", help="Integer primary key or 8-char plaintext prefix.")

    def handle(self, *args, **options):
        from wagtail_mcp_server.models import UserMcpToken  # noqa: PLC0415

        ident = options["token_id"]
        qs = UserMcpToken.objects.all()
        if ident.isdigit():
            try:
                row = qs.get(pk=int(ident))
            except UserMcpToken.DoesNotExist as exc:
                raise CommandError(f"No token with id={ident}") from exc
        else:
            matches = list(qs.filter(token_prefix=ident)[:2])
            if not matches:
                raise CommandError(f"No token with prefix='{ident}'")
            if len(matches) > 1:
                raise CommandError(
                    f"Prefix '{ident}' matches multiple tokens; pass the integer id instead."
                )
            row = matches[0]

        if row.revoked_at is not None:
            self.stdout.write(self.style.WARNING(f"Token id={row.pk} was already revoked."))
            return

        row.revoke()
        self.stdout.write(
            self.style.SUCCESS(f"Revoked token id={row.pk} label='{row.label}'")
        )
