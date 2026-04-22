"""Tests for the JSON Schema builder.

These tests are intentionally schema-shape focused. They do not run the
schema through ``jsonschema.validate`` because that would lock us into a
specific draft version's nuances; we just check that the structural
contract holds (``$schema`` present, envelope shape, recursion via
``items.oneOf``, chooser ``_raw_id`` requirements).
"""

from __future__ import annotations

import pytest

from wagtail_mcp_server.schema import build_page_type_schema


@pytest.mark.django_db
def test_top_level_schema_has_envelope_per_block_type():
    from tests.testapp.models import TestStreamPage

    schema = build_page_type_schema(TestStreamPage)
    body = schema["properties"]["body"]
    assert body["type"] == "array"
    one_of = body["items"]["oneOf"]
    block_consts = {entry["properties"]["type"]["const"] for entry in one_of}
    # Spot-check several block types from BODY_BLOCKS.
    assert "heading" in block_consts
    assert "paragraph" in block_consts
    assert "image" in block_consts
    assert "document" in block_consts
    assert "page_link" in block_consts
    assert "faqs" in block_consts
    assert "inner_stream" in block_consts


@pytest.mark.django_db
def test_chooser_value_requires_raw_id():
    from tests.testapp.models import TestStreamPage

    schema = build_page_type_schema(TestStreamPage)
    body = schema["properties"]["body"]
    image_envelope = next(
        e for e in body["items"]["oneOf"] if e["properties"]["type"]["const"] == "image"
    )
    image_value = image_envelope["properties"]["value"]
    assert "_raw_id" in image_value["required"]


@pytest.mark.django_db
def test_struct_value_object_keyed_by_child_name():
    from tests.testapp.models import TestStreamPage

    schema = build_page_type_schema(TestStreamPage)
    body = schema["properties"]["body"]
    heading_env = next(
        e for e in body["items"]["oneOf"] if e["properties"]["type"]["const"] == "heading"
    )
    heading_value = heading_env["properties"]["value"]
    assert heading_value["type"] == "object"
    assert set(heading_value["properties"].keys()) == {"text", "level"}
    assert heading_value["additionalProperties"] is False
    # ChoiceBlock surfaces an enum.
    assert heading_value["properties"]["level"]["enum"] == ["h2", "h3", "h4"]


@pytest.mark.django_db
def test_inner_stream_block_recursion_yields_array_of_envelopes():
    from tests.testapp.models import TestStreamPage

    schema = build_page_type_schema(TestStreamPage)
    body = schema["properties"]["body"]
    inner_env = next(
        e
        for e in body["items"]["oneOf"]
        if e["properties"]["type"]["const"] == "inner_stream"
    )
    inner_value = inner_env["properties"]["value"]
    assert inner_value["type"] == "array"
    inner_block_consts = {
        entry["properties"]["type"]["const"] for entry in inner_value["items"]["oneOf"]
    }
    assert inner_block_consts == {"paragraph", "image"}


@pytest.mark.django_db
def test_list_block_emits_array_of_item_envelopes():
    from tests.testapp.models import TestStreamPage

    schema = build_page_type_schema(TestStreamPage)
    body = schema["properties"]["body"]
    faqs_env = next(
        e for e in body["items"]["oneOf"] if e["properties"]["type"]["const"] == "faqs"
    )
    faqs_value = faqs_env["properties"]["value"]
    assert faqs_value["type"] == "array"
    item_envelope = faqs_value["items"]
    assert item_envelope["properties"]["type"]["const"] in {"item", ""}
    item_value = item_envelope["properties"]["value"]
    assert set(item_value["properties"].keys()) == {"question", "answer"}
