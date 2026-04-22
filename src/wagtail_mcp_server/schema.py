"""JSON Schema builder for page types and StreamField blocks.

``pages.types.schema`` returns one of these documents per page model so
that an agent can validate a write payload locally before calling
``pages.update``. The schema is JSON Schema draft 2020-12 and uses
``$defs`` + ``$ref`` so recursive blocks (a StreamBlock containing other
StreamBlocks, for instance) do not blow up into infinite documents.

The shape is intentionally close to what a JSON Schema linter / IDE
plugin can validate, not a custom dialect: any standard tooling can read
it, and consumers can run it through ``jsonschema.validate`` as-is.
"""

from __future__ import annotations

from typing import Any

# Common JSON Schema for the canonical envelope. Embedded under $defs and
# referenced by every block-typed slot.
_ENVELOPE_BASE: dict[str, Any] = {
    "type": "object",
    "required": ["type", "value"],
    "properties": {
        "type": {"type": "string"},
        "id": {"type": ["string", "null"]},
    },
}


def build_page_type_schema(model: Any) -> dict[str, Any]:
    """Build a JSON Schema for a Wagtail page model.

    The returned document describes the shape ``pages.update`` accepts for
    that page type. Every field surfaced by the model's ``api_fields`` is
    included; everything else is omitted, matching the read shape.
    """
    from wagtail.fields import StreamField

    defs: dict[str, Any] = {}
    properties: dict[str, Any] = {
        "title": {"type": "string"},
        "slug": {"type": "string"},
    }
    required: list[str] = []

    for field_name in _api_field_names(model):
        try:
            field = model._meta.get_field(field_name)
        except Exception:  # noqa: BLE001 -- not every api_field is a model field
            properties[field_name] = {}
            continue

        if isinstance(field, StreamField):
            properties[field_name] = _streamfield_schema(field, defs)
        else:
            properties[field_name] = _scalar_field_schema(field)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{model._meta.app_label}.{model.__name__}",
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    if defs:
        schema["$defs"] = defs
    return schema


# --------------------------------------------------------------------------- streams


def _streamfield_schema(field: Any, defs: dict[str, Any]) -> dict[str, Any]:
    """Schema for a top-level StreamField -- an array of envelopes."""
    stream_block = field.stream_block
    return {
        "type": "array",
        "items": _stream_items_schema(stream_block, defs),
    }


def _stream_items_schema(stream_block: Any, defs: dict[str, Any]) -> dict[str, Any]:
    """``oneOf`` envelope schemas for every block type in the stream."""
    one_of: list[dict[str, Any]] = []
    child_blocks = getattr(stream_block, "child_blocks", {}) or {}
    for block_name, child_block in child_blocks.items():
        one_of.append(_envelope_schema(block_name, child_block, defs))
    return {"oneOf": one_of} if one_of else {}


def _envelope_schema(
    block_name: str,
    block: Any,
    defs: dict[str, Any],
) -> dict[str, Any]:
    """Schema for one envelope shape: ``{type: const, id, value: <block_value>}``."""
    schema = {
        **_ENVELOPE_BASE,
        "properties": {
            **_ENVELOPE_BASE["properties"],
            "type": {"const": block_name},
            "value": _block_value_schema(block, defs),
        },
    }
    return schema


def _block_value_schema(block: Any, defs: dict[str, Any]) -> dict[str, Any]:
    """Schema for the ``value`` of a single block, dispatched on block type."""
    from wagtail import blocks as wagtail_blocks
    from wagtail.documents.blocks import DocumentChooserBlock
    from wagtail.images.blocks import ImageChooserBlock

    if isinstance(block, wagtail_blocks.RichTextBlock):
        # HTML or Draftail JSON; both serialize to a string here.
        return {"type": "string"}

    if isinstance(block, ImageChooserBlock):
        return _chooser_value_schema(
            extra_props={
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            }
        )

    if isinstance(block, DocumentChooserBlock):
        return _chooser_value_schema()

    if isinstance(block, wagtail_blocks.PageChooserBlock):
        return _chooser_value_schema(
            extra_props={
                "slug": {"type": "string"},
                "url_path": {"type": "string"},
            }
        )

    if isinstance(block, wagtail_blocks.StructBlock):
        return _struct_value_schema(block, defs)

    if isinstance(block, wagtail_blocks.ListBlock):
        return {
            "type": "array",
            "items": _envelope_schema(
                getattr(block.child_block, "name", "") or "item",
                block.child_block,
                defs,
            ),
        }

    if isinstance(block, wagtail_blocks.StreamBlock):
        return {
            "type": "array",
            "items": _stream_items_schema(block, defs),
        }

    return _primitive_value_schema(block)


def _struct_value_schema(block: Any, defs: dict[str, Any]) -> dict[str, Any]:
    """Schema for a StructBlock value -- an object keyed by child name."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    child_blocks = getattr(block, "child_blocks", {}) or {}
    for child_name, child_block in child_blocks.items():
        properties[child_name] = _block_value_schema(child_block, defs)
        # Wagtail exposes ``required`` directly on the block (it forwards to
        # the underlying form field). Older code paths stored it under meta.
        if getattr(child_block, "required", getattr(child_block.meta, "required", False)):
            required.append(child_name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _chooser_value_schema(*, extra_props: dict[str, Any] | None = None) -> dict[str, Any]:
    """Schema for a chooser-block value (Image/Page/Document)."""
    properties: dict[str, Any] = {
        "_raw_id": {"type": ["integer", "null"]},
        "id": {"type": ["integer", "null"]},
        "title": {"type": "string"},
        "url": {"type": "string"},
    }
    if extra_props:
        properties.update(extra_props)
    return {
        "type": "object",
        "required": ["_raw_id"],
        "properties": properties,
    }


def _primitive_value_schema(block: Any) -> dict[str, Any]:
    """Schema for a primitive Wagtail block (CharBlock, IntegerBlock, etc.)."""
    from wagtail import blocks as wagtail_blocks

    if isinstance(block, wagtail_blocks.BooleanBlock):
        return {"type": "boolean"}
    if isinstance(
        block,
        wagtail_blocks.IntegerBlock | wagtail_blocks.FloatBlock | wagtail_blocks.DecimalBlock,
    ):
        return {"type": "number"}
    if isinstance(block, wagtail_blocks.URLBlock):
        return {"type": "string", "format": "uri"}
    if isinstance(block, wagtail_blocks.EmailBlock):
        return {"type": "string", "format": "email"}
    if isinstance(block, wagtail_blocks.DateBlock):
        return {"type": "string", "format": "date"}
    if isinstance(block, wagtail_blocks.DateTimeBlock):
        return {"type": "string", "format": "date-time"}
    if isinstance(block, wagtail_blocks.ChoiceBlock):
        # Wagtail stores choices on the underlying form ``field`` rather than
        # the block instance; fall back to ``block.choices`` for older shapes.
        raw_choices = (
            getattr(getattr(block, "field", None), "choices", None)
            or getattr(block, "choices", None)
            or []
        )
        choices = [c[0] for c in raw_choices if c and c[0]]
        if choices:
            return {"type": "string", "enum": choices}
        return {"type": "string"}
    # CharBlock, TextBlock, RawHTMLBlock, anything else string-like.
    return {"type": "string"}


# ---------------------------------------------------------------------------- scalars


def _scalar_field_schema(field: Any) -> dict[str, Any]:
    """Best-effort JSON Schema for a non-StreamField model field."""
    from django.db import models

    if isinstance(field, models.BooleanField):
        return {"type": "boolean"}
    if isinstance(field, models.IntegerField | models.AutoField):
        return {"type": "integer"}
    if isinstance(field, models.FloatField):
        return {"type": "number"}
    if isinstance(field, models.DateTimeField):
        return {"type": "string", "format": "date-time"}
    if isinstance(field, models.DateField):
        return {"type": "string", "format": "date"}
    if isinstance(field, models.URLField):
        return {"type": "string", "format": "uri"}
    if isinstance(field, models.EmailField):
        return {"type": "string", "format": "email"}
    if isinstance(field, models.ForeignKey):
        return {"type": ["integer", "null"]}
    return {"type": "string"}


def _api_field_names(model: Any) -> list[str]:
    """Mirror of ``PageSerializer._field_names`` for the model side."""
    api_fields = getattr(model, "api_fields", None) or []
    out: list[str] = []
    for entry in api_fields:
        if isinstance(entry, str):
            out.append(entry)
        else:
            name = getattr(entry, "name", None)
            if name:
                out.append(name)
    return out
