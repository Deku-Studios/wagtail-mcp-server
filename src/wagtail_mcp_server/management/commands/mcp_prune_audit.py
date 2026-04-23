"""``manage.py mcp_prune_audit``: drop aged ``ToolCall`` audit rows.

Enforces ``WAGTAIL_MCP_SERVER['AUDIT']['RETENTION_DAYS']`` against the
``ToolCall`` table. Deletes rows whose ``created_at`` is older than the
retention window.

Examples::

    # Preview what would be deleted.
    python manage.py mcp_prune_audit --dry-run

    # Actually prune, 5000 rows per batch.
    python manage.py mcp_prune_audit --batch-size 5000

    # Override the retention window for this run only.
    python manage.py mcp_prune_audit --older-than 30

The command deletes in bounded batches so it can run on large tables
without loading the full candidate set into memory. Each batch is its
own transaction via the `DELETE ... LIMIT`-equivalent queryset slice,
so interrupting mid-run is safe: the next invocation resumes from
wherever the clock has advanced to.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from wagtail_mcp_server.settings import get_config

DEFAULT_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Delete ToolCall audit rows older than AUDIT.RETENTION_DAYS. "
        "Use --dry-run to preview without deleting."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without touching the DB.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=(
                f"Rows to delete per transaction batch (default {DEFAULT_BATCH_SIZE})."
            ),
        )
        parser.add_argument(
            "--older-than",
            type=int,
            default=None,
            metavar="DAYS",
            help=(
                "Override AUDIT.RETENTION_DAYS for this run. Rows older than "
                "DAYS will be pruned."
            ),
        )

    def handle(self, *args, **options):
        # Local import so Django app registry is ready before we touch models.
        from wagtail_mcp_server.models import ToolCall  # noqa: PLC0415

        cfg = get_config()
        retention_days = options["older_than"]
        if retention_days is None:
            retention_days = cfg["AUDIT"]["RETENTION_DAYS"]

        if retention_days is None or retention_days <= 0:
            raise CommandError(
                "Retention window must be a positive integer. Got "
                f"retention_days={retention_days!r}."
            )

        batch_size = options["batch_size"]
        if batch_size <= 0:
            raise CommandError(
                f"--batch-size must be positive, got {batch_size!r}."
            )

        cutoff = timezone.now() - timedelta(days=retention_days)
        qs = ToolCall.objects.filter(created_at__lt=cutoff)
        candidate_count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                self.style.NOTICE(
                    f"[dry-run] {candidate_count} ToolCall rows older than "
                    f"{cutoff.isoformat()} (retention={retention_days}d). "
                    "No rows deleted."
                )
            )
            return

        if candidate_count == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No ToolCall rows older than {cutoff.isoformat()} "
                    f"(retention={retention_days}d). Nothing to do."
                )
            )
            return

        deleted_total = 0
        while True:
            # Grab the next batch of PKs, then delete by id. This keeps the
            # delete query cheap and index-friendly on large tables.
            batch_pks = list(
                ToolCall.objects.filter(created_at__lt=cutoff)
                .order_by("created_at")
                .values_list("pk", flat=True)[:batch_size]
            )
            if not batch_pks:
                break
            with transaction.atomic():
                deleted_rows, _ = ToolCall.objects.filter(pk__in=batch_pks).delete()
            deleted_total += deleted_rows
            self.stdout.write(
                f"... pruned batch of {deleted_rows} (running total {deleted_total})"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {deleted_total} ToolCall rows older than "
                f"{cutoff.isoformat()} (retention={retention_days}d)."
            )
        )
