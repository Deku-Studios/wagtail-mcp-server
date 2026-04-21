"""Database models for wagtail-mcp-server.

Three models:

``UserMcpToken``
    Per-agent API token bound to a single Django user. Stored hashed so a
    database dump does not yield live credentials. The plaintext is shown
    once at issue time and never again.

``ToolCall``
    Audit log of every tool invocation: user, toolset, tool, inputs,
    outputs, latency, outcome. Retention is governed by
    ``AUDIT.RETENTION_DAYS``.

``AgentScratchpad``
    Key-value store scoped to a (user, namespace) pair. Lets an agent
    leave notes for itself across sessions without polluting Wagtail's
    own tables. Optional; unused by core toolsets in v0.1.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone


def _hash_token(plaintext: str) -> str:
    """SHA-256 hash used for storage. Plaintext is never persisted."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class UserMcpToken(models.Model):
    """One API token per (agent, user) pair."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mcp_tokens",
        on_delete=models.CASCADE,
    )
    label = models.CharField(
        max_length=120,
        help_text="Human-readable label, typically the agent name.",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(
        max_length=8,
        db_index=True,
        help_text="First 8 chars of the plaintext, stored for lookup UX.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "MCP user token"
        verbose_name_plural = "MCP user tokens"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        state = "revoked" if self.revoked_at else "active"
        return f"{self.label} ({self.token_prefix}..., {state})"

    @staticmethod
    def hash_token(plaintext: str) -> str:
        """Convenience for lookups. Equivalent to ``_hash_token``."""
        return _hash_token(plaintext)

    @classmethod
    def issue(cls, user, label: str) -> tuple["UserMcpToken", str]:
        """Mint a new token. Returns ``(row, plaintext)``; plaintext is
        shown once and never persisted."""
        plaintext = secrets.token_urlsafe(32)
        row = cls.objects.create(
            user=user,
            label=label,
            token_hash=_hash_token(plaintext),
            token_prefix=plaintext[:8],
        )
        return row, plaintext

    def mark_used(self) -> None:
        self.last_used_at = timezone.now()
        type(self).objects.filter(pk=self.pk).update(last_used_at=self.last_used_at)

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class ToolCall(models.Model):
    """Audit log for every tool invocation."""

    OUTCOME_OK = "ok"
    OUTCOME_ERROR = "error"
    OUTCOME_DENIED = "denied"
    OUTCOME_CHOICES: ClassVar = [
        (OUTCOME_OK, "ok"),
        (OUTCOME_ERROR, "error"),
        (OUTCOME_DENIED, "denied"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mcp_tool_calls",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    token = models.ForeignKey(
        UserMcpToken,
        related_name="tool_calls",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    toolset = models.CharField(max_length=64, db_index=True)
    tool = models.CharField(max_length=128, db_index=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, db_index=True)
    latency_ms = models.PositiveIntegerField(default=0)
    input_bytes = models.PositiveIntegerField(default=0)
    output_bytes = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "MCP tool call"
        verbose_name_plural = "MCP tool calls"
        ordering: ClassVar = ["-created_at"]
        indexes: ClassVar = [
            models.Index(fields=["toolset", "tool", "-created_at"]),
        ]


class AgentScratchpad(models.Model):
    """Per-user, per-namespace scratchpad. Optional in v0.1."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mcp_scratchpads",
        on_delete=models.CASCADE,
    )
    namespace = models.CharField(max_length=64, db_index=True)
    key = models.CharField(max_length=256)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together: ClassVar = [("user", "namespace", "key")]
        verbose_name = "MCP agent scratchpad"
        verbose_name_plural = "MCP agent scratchpads"
