"""Initial migration for wagtail-mcp-server.

Creates ``UserMcpToken``, ``ToolCall``, and ``AgentScratchpad``.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserMcpToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=120)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("token_prefix", models.CharField(db_index=True, max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mcp_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "MCP user token",
                "verbose_name_plural": "MCP user tokens",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ToolCall",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("toolset", models.CharField(db_index=True, max_length=64)),
                ("tool", models.CharField(db_index=True, max_length=128)),
                (
                    "outcome",
                    models.CharField(
                        choices=[("ok", "ok"), ("error", "error"), ("denied", "denied")],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("input_bytes", models.PositiveIntegerField(default=0)),
                ("output_bytes", models.PositiveIntegerField(default=0)),
                ("error_code", models.CharField(blank=True, default="", max_length=64)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "token",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tool_calls",
                        to="wagtail_mcp_server.usermcptoken",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mcp_tool_calls",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "MCP tool call",
                "verbose_name_plural": "MCP tool calls",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="toolcall",
            index=models.Index(
                fields=["toolset", "tool", "-created_at"],
                name="wms_toolcall_tstool_ca_idx",
            ),
        ),
        migrations.CreateModel(
            name="AgentScratchpad",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("namespace", models.CharField(db_index=True, max_length=64)),
                ("key", models.CharField(max_length=256)),
                ("value", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mcp_scratchpads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "MCP agent scratchpad",
                "verbose_name_plural": "MCP agent scratchpads",
                "unique_together": {("user", "namespace", "key")},
            },
        ),
    ]
