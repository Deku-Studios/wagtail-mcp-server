"""StreamField serializer and validator.

Symmetric envelope
==================

Every block, at every depth, is represented on the wire as::

    {"type": "<block_type>", "id": "<block_id>", "value": <block_value>}

``value`` is shaped per block kind:

    - ``CharBlock`` / ``TextBlock`` / ``IntegerBlock`` / etc.: the scalar.
    - ``RichTextBlock``: a string whose format is governed by
      ``WAGTAIL_MCP_SERVER["RICHTEXT_FORMAT"]`` (``"html"`` default,
      ``"draftail"`` opt-in).
    - ``StructBlock``: a dict of ``{child_name: <envelope>}``.
    - ``ListBlock``: a list of ``<envelope>`` entries.
    - ``StreamBlock``: a list of ``<envelope>`` entries.
    - ``ChooserBlock`` (Page, Image, Document): a dict with a
      denormalized preview and ``_raw_id`` as the canonical write key.
      Writers set ``_raw_id``; extra fields are ignored on write but
      returned on read.

Strict writes
=============

When ``WAGTAIL_MCP_SERVER["WRITE_VALIDATION"] == "strict"`` (default),
unknown top-level keys, unknown block types, and unknown struct child
names all raise :class:`StreamFieldValidationError`. The error carries a
closed-vocabulary ``code`` plus the ``path`` into the stream and what
was expected vs. what was got, so the calling agent can self-correct.

Under ``"permissive"``, unknown keys and block types are dropped with a
warning. Use sparingly; strict is the supported mode.

This module is the v0 scaffold: helpers and error types are in place so
other modules can import them. The walk implementation lands alongside
``PageQueryToolset`` (read path) and ``PageWriteToolset`` (write path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Envelope = dict[str, Any]
StreamValue = list[Envelope]

ErrorCode = Literal[
    "unknown_block_type",
    "unknown_child",
    "missing_required",
    "type_mismatch",
    "invalid_chooser_ref",
    "invalid_richtext",
    "envelope_shape",
]


@dataclass(slots=True)
class StreamFieldError:
    """One validation error, located within a stream."""

    code: ErrorCode
    path: str
    expected: str
    got: str
    message: str = ""


class StreamFieldValidationError(ValueError):
    """Raised when a write payload fails validation in strict mode."""

    def __init__(self, errors: list[StreamFieldError]) -> None:
        self.errors = errors
        summary = "; ".join(f"{e.path}: {e.code} (expected {e.expected}, got {e.got})" for e in errors)
        super().__init__(f"StreamField validation failed: {summary}")


@dataclass(slots=True)
class SerializeOptions:
    """Read-time knobs."""

    richtext_format: Literal["html", "draftail"] = "html"
    include_chooser_preview: bool = True


@dataclass(slots=True)
class DeserializeOptions:
    """Write-time knobs."""

    validation: Literal["strict", "permissive"] = "strict"
    errors: list[StreamFieldError] = field(default_factory=list)


def make_envelope(block_type: str, block_id: str | None, value: Any) -> Envelope:
    """Build an envelope in the canonical order. Used by the read path."""
    return {"type": block_type, "id": block_id or "", "value": value}


def is_envelope(obj: Any) -> bool:
    """True if ``obj`` looks like an envelope dict."""
    return (
        isinstance(obj, dict)
        and "type" in obj
        and "value" in obj
        and isinstance(obj["type"], str)
    )


# Walk implementations live in the pages_query / pages_write toolsets in v0.1;
# this module exports only the envelope contract + error types so they can be
# imported and referenced from other modules, documentation, and tests.
