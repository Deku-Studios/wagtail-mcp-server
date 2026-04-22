"""Strict/permissive validation tests for the StreamField write-path.

The read path (serialize) is exercised in ``test_streamfield_walk.py`` and
the envelope shape contract is exercised in ``test_streamfield_envelope.py``.
This file covers the inverse direction: agent-shaped envelopes going back
into Wagtail-native values, and what happens when an envelope is malformed.
"""

from __future__ import annotations

import pytest

from tests.testapp.models import TestStreamPage
from wagtail_mcp_server.serializers.streamfield import (
    DeserializeOptions,
    StreamFieldValidationError,
    deserialize_streamfield,
)


def _block(page_model=TestStreamPage):
    """Return the bound StreamBlock for ``TestStreamPage.body``."""
    field = page_model._meta.get_field("body")
    return field.stream_block


# --------------------------------------------------------------------- happy path


def test_deserialize_primitive_passthrough():
    block = _block()
    out = deserialize_streamfield(
        block,
        [{"type": "number", "value": 42}],
    )
    assert out == [("number", 42)]


def test_deserialize_struct_unwraps_children():
    block = _block()
    out = deserialize_streamfield(
        block,
        [{"type": "heading", "value": {"text": "Hi", "level": "h3"}}],
    )
    assert out[0][0] == "heading"
    # Struct deserialization yields a StructValue or dict; children are
    # accessible by name.
    struct_value = out[0][1]
    assert struct_value["text"] == "Hi"
    assert struct_value["level"] == "h3"


def test_deserialize_listblock_children_are_rewrapped():
    block = _block()
    out = deserialize_streamfield(
        block,
        [
            {
                "type": "faqs",
                "value": [
                    {
                        "type": "item",
                        "value": {"question": "Q?", "answer": "<p>A.</p>"},
                    }
                ],
            }
        ],
    )
    assert out[0][0] == "faqs"
    # ListBlock deserializes into a Python list of child values.
    assert len(out[0][1]) == 1


def test_deserialize_nested_streamblock_recurses():
    block = _block()
    out = deserialize_streamfield(
        block,
        [
            {
                "type": "inner_stream",
                "value": [{"type": "paragraph", "value": "<p>Nested</p>"}],
            }
        ],
    )
    # inner_stream's value is itself a list of (block_type, value) tuples.
    assert out[0][0] == "inner_stream"


# ---------------------------------------------------------------------- strict mode


def test_unknown_block_type_raises_in_strict_mode():
    block = _block()
    with pytest.raises(StreamFieldValidationError) as exc_info:
        deserialize_streamfield(
            block,
            [{"type": "definitely_not_a_block", "value": 1}],
        )
    codes = {e.code for e in exc_info.value.errors}
    assert "unknown_block_type" in codes


def test_missing_envelope_type_raises():
    block = _block()
    with pytest.raises(StreamFieldValidationError) as exc_info:
        deserialize_streamfield(block, [{"value": "oops"}])
    codes = {e.code for e in exc_info.value.errors}
    assert "envelope_shape" in codes


def test_struct_unknown_child_raises():
    block = _block()
    with pytest.raises(StreamFieldValidationError) as exc_info:
        deserialize_streamfield(
            block,
            [{"type": "heading", "value": {"text": "Hi", "bogus_child": 1}}],
        )
    codes = {e.code for e in exc_info.value.errors}
    assert "unknown_child" in codes


def test_struct_missing_required_child_raises():
    """StructBlock child ``text`` is required=True; omitting it must raise."""
    block = _block()
    with pytest.raises(StreamFieldValidationError) as exc_info:
        deserialize_streamfield(
            block,
            [{"type": "heading", "value": {"level": "h2"}}],
        )
    codes = {e.code for e in exc_info.value.errors}
    assert "missing_required" in codes


# ------------------------------------------------------------------ permissive mode


def test_permissive_drops_unknown_block_type():
    block = _block()
    out = deserialize_streamfield(
        block,
        [
            {"type": "number", "value": 1},
            {"type": "garbage_block", "value": "x"},
            {"type": "number", "value": 2},
        ],
        options=DeserializeOptions(validation="permissive"),
    )
    # The garbage block is dropped; the surrounding valid blocks come through.
    types = [t for (t, _v) in out]
    assert "garbage_block" not in types
    assert types.count("number") == 2


# ---------------------------------------------------------------------- error shape


def test_errors_include_path_for_nested_faults():
    """A fault inside a ListBlock should carry a path pointing into the list."""
    block = _block()
    with pytest.raises(StreamFieldValidationError) as exc_info:
        deserialize_streamfield(
            block,
            [
                {
                    "type": "faqs",
                    "value": [
                        {"type": "item", "value": {"answer": "<p>A.</p>"}},
                    ],
                }
            ],
        )
    # At least one error must point somewhere inside the stream/list.
    paths = [e.path for e in exc_info.value.errors]
    assert any("$" in p for p in paths)
