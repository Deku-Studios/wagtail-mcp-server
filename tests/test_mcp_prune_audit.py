"""Tests for the ``mcp_prune_audit`` management command.

Covers:
    - ``--dry-run`` reports the candidate count without deleting.
    - A live prune deletes rows older than the retention window and
      leaves fresh rows alone.
    - ``--batch-size`` caps the per-transaction delete count.
    - The 0-row fast path exits clean without touching the DB.
    - ``AUDIT.RETENTION_DAYS`` drives the cutoff when ``--older-than``
      is not supplied.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from wagtail_mcp_server import settings as mcp_settings
from wagtail_mcp_server.models import ToolCall


def _make_call(age_days: float, *, tool: str = "pages.list") -> ToolCall:
    """Create a ToolCall whose ``created_at`` is ``age_days`` old."""
    row = ToolCall.objects.create(
        toolset="pages_query",
        tool=tool,
        outcome=ToolCall.OUTCOME_OK,
        latency_ms=1,
        input_bytes=0,
        output_bytes=0,
    )
    # ``auto_now_add`` pins created_at to now. Rewrite it with a direct
    # update so the retention window actually catches this row.
    ToolCall.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(days=age_days)
    )
    return ToolCall.objects.get(pk=row.pk)


@pytest.fixture(autouse=True)
def _reset_cached_config():
    """Each test reads a fresh config dict."""
    mcp_settings.reset_cache()
    yield
    mcp_settings.reset_cache()


@pytest.mark.django_db
def test_dry_run_reports_candidates_without_deleting():
    old = _make_call(age_days=120)
    fresh = _make_call(age_days=1)

    out = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", "--dry-run", stdout=out)

    assert "[dry-run]" in out.getvalue()
    assert "1 ToolCall rows older than" in out.getvalue()
    # Nothing deleted.
    assert ToolCall.objects.filter(pk=old.pk).exists()
    assert ToolCall.objects.filter(pk=fresh.pk).exists()


@pytest.mark.django_db
def test_actual_prune_deletes_only_aged_rows():
    old_a = _make_call(age_days=120, tool="pages.list")
    old_b = _make_call(age_days=95, tool="pages.get")
    fresh = _make_call(age_days=30, tool="pages.list")

    out = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", stdout=out)

    assert "Pruned 2 ToolCall rows" in out.getvalue()
    assert not ToolCall.objects.filter(pk=old_a.pk).exists()
    assert not ToolCall.objects.filter(pk=old_b.pk).exists()
    assert ToolCall.objects.filter(pk=fresh.pk).exists()


@pytest.mark.django_db
def test_batch_size_honored():
    # Seed 5 aged rows, prune in batches of 2, expect 3 reported batches.
    for _ in range(5):
        _make_call(age_days=120)

    out = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", "--batch-size", "2", stdout=out)

    output = out.getvalue()
    # One batch of 2, one batch of 2, one batch of 1.
    assert output.count("pruned batch of 2") == 2
    assert output.count("pruned batch of 1") == 1
    assert "Pruned 5 ToolCall rows" in output
    assert ToolCall.objects.count() == 0


@pytest.mark.django_db
def test_zero_row_fast_path_exits_clean():
    # No aged rows; only a fresh one.
    _make_call(age_days=5)

    out = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", stdout=out)

    assert "Nothing to do." in out.getvalue()
    assert ToolCall.objects.count() == 1


@pytest.mark.django_db
def test_retention_days_from_settings_drives_cutoff():
    # 40-day-old row, retention=30 should prune; retention=90 should not.
    row = _make_call(age_days=40)

    out_short = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 30}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", stdout=out_short)
    assert not ToolCall.objects.filter(pk=row.pk).exists()

    # Seed another aged row, confirm 90-day retention leaves it alone.
    row2 = _make_call(age_days=40)
    out_long = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", stdout=out_long)
    assert ToolCall.objects.filter(pk=row2.pk).exists()
    assert "Nothing to do." in out_long.getvalue()


@pytest.mark.django_db
def test_older_than_flag_overrides_setting():
    row = _make_call(age_days=20)

    out = StringIO()
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        call_command("mcp_prune_audit", "--older-than", "10", stdout=out)

    assert not ToolCall.objects.filter(pk=row.pk).exists()
    assert "Pruned 1 ToolCall rows" in out.getvalue()


@pytest.mark.django_db
def test_non_positive_batch_size_raises():
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        with pytest.raises(CommandError):
            call_command("mcp_prune_audit", "--batch-size", "0")


@pytest.mark.django_db
def test_non_positive_older_than_raises():
    with override_settings(WAGTAIL_MCP_SERVER={"AUDIT": {"RETENTION_DAYS": 90}}):
        mcp_settings.reset_cache()
        with pytest.raises(CommandError):
            call_command("mcp_prune_audit", "--older-than", "0")
