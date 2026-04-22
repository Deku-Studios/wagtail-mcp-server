"""Round-trip tests for the StreamField read-path walk.

Each block shape declared in ``tests.testapp.models.BODY_BLOCKS`` gets
exercised here. The contract under test is the envelope shape from spec
section 6.6: ``{type, id, value}`` at every depth, with StructBlock
children unwrapped and List/Stream children re-wrapped.
"""

from __future__ import annotations

import pytest

from wagtail_mcp_server.serializers.streamfield import (
    SerializeOptions,
    is_envelope,
    serialize_streamfield,
)

# ---------------------------------------------------------------------------- helpers


def _populate(page, body):
    """Replace the page's body and persist."""
    page.body = body
    page.save_revision().publish()
    page.refresh_from_db()
    return page


# ----------------------------------------------------------------- primitive blocks


@pytest.mark.django_db
def test_richtext_renders_to_html_string(stream_page):
    page = _populate(stream_page, [("paragraph", "<p>Hello <strong>world</strong></p>")])
    out = serialize_streamfield(page.body)
    assert len(out) == 1
    env = out[0]
    assert env["type"] == "paragraph"
    assert isinstance(env["value"], str)
    assert "Hello" in env["value"]
    assert "<strong>" in env["value"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "block_name,raw_value",
    [
        ("text", "plain text"),
        ("number", 42),
        ("flag", True),
        ("link", "https://example.com/"),
    ],
)
def test_primitive_block_round_trips(stream_page, block_name, raw_value):
    page = _populate(stream_page, [(block_name, raw_value)])
    out = serialize_streamfield(page.body)
    assert out[0]["type"] == block_name
    assert out[0]["value"] == raw_value


# ------------------------------------------------------------------ struct + list


@pytest.mark.django_db
def test_struct_block_unwraps_children(stream_page):
    page = _populate(
        stream_page,
        [("heading", {"text": "Section 1", "level": "h3"})],
    )
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "heading"
    # Per spec 6.6: struct children are NOT envelope-wrapped.
    assert env["value"] == {"text": "Section 1", "level": "h3"}


@pytest.mark.django_db
def test_list_block_wraps_each_item(stream_page):
    page = _populate(
        stream_page,
        [
            (
                "faqs",
                [
                    {"question": "Why?", "answer": "<p>Because</p>"},
                    {"question": "How?", "answer": "<p>Like so</p>"},
                ],
            )
        ],
    )
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "faqs"
    assert isinstance(env["value"], list)
    assert len(env["value"]) == 2
    for item in env["value"]:
        assert is_envelope(item)
        # The list child block is the FAQItem StructBlock; its value is unwrapped.
        assert "question" in item["value"]
        assert "answer" in item["value"]


# ------------------------------------------------------------------- stream nesting


@pytest.mark.django_db
def test_inner_stream_block_walks_recursively(stream_page):
    page = _populate(
        stream_page,
        [
            (
                "inner_stream",
                [
                    ("paragraph", "<p>One</p>"),
                    ("paragraph", "<p>Two</p>"),
                ],
            )
        ],
    )
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "inner_stream"
    assert isinstance(env["value"], list)
    assert len(env["value"]) == 2
    for child in env["value"]:
        assert is_envelope(child)
        assert child["type"] == "paragraph"
        assert "<p>" in child["value"]


# ------------------------------------------------------------------------- choosers


@pytest.mark.django_db
def test_image_chooser_block_denormalizes(stream_page, image_obj):
    page = _populate(stream_page, [("image", image_obj)])
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "image"
    assert env["value"]["_raw_id"] == image_obj.pk
    assert env["value"]["id"] == image_obj.pk
    assert env["value"]["title"] == "Cover"
    assert "rendition_urls" in env["value"]


@pytest.mark.django_db
def test_document_chooser_block_denormalizes(stream_page, document_obj):
    page = _populate(stream_page, [("document", document_obj)])
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "document"
    assert env["value"]["_raw_id"] == document_obj.pk
    assert env["value"]["title"] == "Whitepaper"
    assert env["value"]["url"].endswith(".pdf")


@pytest.mark.django_db
def test_page_chooser_block_denormalizes(stream_page, home_page):
    page = _populate(stream_page, [("page_link", home_page)])
    out = serialize_streamfield(page.body)
    env = out[0]
    assert env["type"] == "page_link"
    assert env["value"]["_raw_id"] == home_page.pk
    assert env["value"]["slug"] == "test-home"


@pytest.mark.django_db
def test_chooser_preview_can_be_disabled(stream_page, image_obj):
    page = _populate(stream_page, [("image", image_obj)])
    options = SerializeOptions(include_chooser_preview=False)
    out = serialize_streamfield(page.body, options=options)
    env = out[0]
    # Only _raw_id when preview is off; agents who only need the id pay nothing extra.
    assert env["value"] == {"_raw_id": image_obj.pk}
