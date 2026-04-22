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
    - ``StructBlock``: a dict of ``{child_name: <rendered_value>}``. Children
      are NOT envelope-wrapped because they have no id and their type is
      pinned by the parent schema. A struct child that is itself a List or
      Stream still yields a list of envelopes (those children have ids).
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
        summary = "; ".join(
            f"{e.path}: {e.code} (expected {e.expected}, got {e.got})" for e in errors
        )
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


# ---------------------------------------------------------------------------
# Read-path walk
# ---------------------------------------------------------------------------
#
# These imports are deferred to the call sites of the walk functions so that
# the module remains importable in environments that have not configured
# Django or installed wagtail.images / wagtail.documents (e.g. doc tooling
# that just wants the error types). Walk functions blow up loudly if Wagtail
# is not actually present, which is the right behavior at runtime.


def serialize_streamfield(
    stream_value: Any,
    options: SerializeOptions | None = None,
) -> StreamValue:
    """Walk a Wagtail ``StreamField`` value and return a list of envelopes.

    ``stream_value`` is the value Django/Wagtail hands back when you read
    ``page.body`` for a ``StreamField`` attribute. Each child yielded by the
    iterator is a ``StreamChild`` exposing ``block_type``, ``id``, ``block``,
    and ``value`` attributes; we convert each into the canonical envelope
    by dispatching on the bound ``block``.
    """
    options = options or SerializeOptions()
    out: StreamValue = []
    for child in stream_value:
        block_type = getattr(child, "block_type", "") or ""
        block_id = getattr(child, "id", None)
        block = getattr(child, "block", None)
        value = getattr(child, "value", None)
        rendered = serialize_block(block, value, options=options)
        out.append(make_envelope(block_type, block_id, rendered))
    return out


def serialize_block(
    block: Any,
    value: Any,
    *,
    options: SerializeOptions | None = None,
) -> Any:
    """Render a single block value into its on-the-wire shape.

    Dispatches on the block class:

    - ``RichTextBlock`` -> string (HTML or Draftail per options)
    - ``StructBlock`` -> ``{child_name: <rendered_value>}`` (children NOT
      envelope-wrapped; see ``serialize_streamfield`` docstring)
    - ``ListBlock`` -> ``[<envelope>, ...]``
    - ``StreamBlock`` -> ``[<envelope>, ...]``
    - ``ImageChooserBlock`` -> denormalized image dict
    - ``DocumentChooserBlock`` -> denormalized document dict
    - ``PageChooserBlock`` -> denormalized page-reference dict
    - everything else -> the raw scalar (CharBlock, IntegerBlock, etc.)
    """
    options = options or SerializeOptions()

    # Local imports keep import-time light and let modules that only want
    # the error types load without a fully configured Wagtail environment.
    from wagtail import blocks as wagtail_blocks
    from wagtail.documents.blocks import DocumentChooserBlock
    from wagtail.images.blocks import ImageChooserBlock

    from .document import serialize_document
    from .image import serialize_image
    from .page_ref import serialize_page_ref

    if block is None:
        return value

    if isinstance(block, wagtail_blocks.RichTextBlock):
        return _render_richtext(value, options.richtext_format)

    if isinstance(block, ImageChooserBlock):
        if not options.include_chooser_preview:
            return {"_raw_id": getattr(value, "pk", None)}
        return serialize_image(value)

    if isinstance(block, DocumentChooserBlock):
        if not options.include_chooser_preview:
            return {"_raw_id": getattr(value, "pk", None)}
        return serialize_document(value)

    if isinstance(block, wagtail_blocks.PageChooserBlock):
        if not options.include_chooser_preview:
            return {"_raw_id": getattr(value, "pk", None)}
        return serialize_page_ref(value)

    if isinstance(block, wagtail_blocks.StructBlock):
        return _serialize_struct(block, value, options=options)

    if isinstance(block, wagtail_blocks.ListBlock):
        return _serialize_list(block, value, options=options)

    if isinstance(block, wagtail_blocks.StreamBlock):
        return serialize_streamfield(value, options=options)

    # Fallthrough: primitive (CharBlock, IntegerBlock, BooleanBlock, etc.).
    # Wagtail already hands us a JSON-friendly Python scalar here.
    return value


def _render_richtext(value: Any, fmt: Literal["html", "draftail"]) -> str:
    """Render a RichTextBlock value to either HTML or Draftail JSON."""
    if value is None:
        return ""
    if fmt == "draftail":
        # Draftail contentstate conversion lives in wagtail.admin.rich_text;
        # importing lazily so library users who only care about HTML do not
        # pay the wagtail.admin import cost at module import time.
        try:
            from wagtail.admin.rich_text.converters.contentstate import (
                ContentstateConverter,
            )
            from wagtail.rich_text import features as feature_registry

            features = feature_registry.get_default_features()
            converter = ContentstateConverter(features=features)
            source = getattr(value, "source", value)
            return converter.from_database_format(str(source))
        except Exception:  # noqa: BLE001 -- fall back to HTML if draftail unavailable
            return str(value)
    return str(value)


def _serialize_struct(
    block: Any,
    value: Any,
    *,
    options: SerializeOptions,
) -> dict[str, Any]:
    """Render a StructBlock value as ``{child_name: <rendered_value>}``.

    Per spec section 6.6: children are not wrapped in an envelope. The
    parent schema pins the type and StructBlock children have no id.
    A child that is itself a List/Stream still yields a list of envelopes
    because list/stream items DO have ids.
    """
    out: dict[str, Any] = {}
    child_blocks = getattr(block, "child_blocks", {}) or {}
    for child_name, child_block in child_blocks.items():
        child_value = _struct_child_value(value, child_name)
        out[child_name] = serialize_block(child_block, child_value, options=options)
    return out


def _struct_child_value(value: Any, child_name: str) -> Any:
    """StructBlock values quack like dicts but may also be StructValue."""
    if value is None:
        return None
    try:
        return value[child_name]
    except (KeyError, TypeError):
        return getattr(value, child_name, None)


def _serialize_list(
    block: Any,
    value: Any,
    *,
    options: SerializeOptions,
) -> list[Envelope]:
    """Render a ListBlock value as a list of envelopes.

    Wagtail >=2.16 ListBlock values yield ``ListValue.ListChild`` instances
    that expose ``.value`` and ``.id``; older shapes yield raw values without
    an id. We tolerate both and synthesize an empty id for the older shape
    so the envelope contract holds.
    """
    out: list[Envelope] = []
    child_block = getattr(block, "child_block", None)
    child_type = getattr(child_block, "name", "") or ""
    for child in value or []:
        if hasattr(child, "value") and hasattr(child, "id"):
            child_id = child.id
            child_value = child.value
        else:
            child_id = None
            child_value = child
        rendered = serialize_block(child_block, child_value, options=options)
        out.append(make_envelope(child_type, child_id, rendered))
    return out
