"""Test-only Wagtail page models.

The single ``TestStreamPage`` body field exercises every block shape the
serializer needs to handle: primitive blocks, RichText, StructBlock,
ListBlock, StreamBlock (including a nested StreamBlock to prove the walk
is recursive), and all three ChooserBlocks (image, document, page).

If you add a new block shape to ``serializers/streamfield.py``, add a
representative entry to ``BODY_BLOCKS`` here and a round-trip test in
``tests/test_streamfield_walk.py``.
"""

from __future__ import annotations

from django.db import models
from wagtail import blocks
from wagtail.api import APIField
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.fields import StreamField
from wagtail.images.api.fields import ImageRenditionField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Page
from wagtail.snippets.models import register_snippet


class HeadingStruct(blocks.StructBlock):
    text = blocks.CharBlock(required=True, max_length=255)
    level = blocks.ChoiceBlock(
        choices=[("h2", "H2"), ("h3", "H3"), ("h4", "H4")],
        default="h2",
    )

    class Meta:
        icon = "title"
        label = "Heading"


class CTAStruct(blocks.StructBlock):
    label = blocks.CharBlock(required=True, max_length=80)
    url = blocks.URLBlock(required=True)
    is_primary = blocks.BooleanBlock(required=False, default=True)

    class Meta:
        icon = "link"
        label = "CTA"


class FAQItem(blocks.StructBlock):
    question = blocks.CharBlock(required=True)
    answer = blocks.RichTextBlock(required=True)


# Inner stream proves StreamBlock recursion. Items can be paragraphs or
# image chooser blocks, both of which are themselves exercised at the
# top level too.
INNER_STREAM_BLOCKS = [
    ("paragraph", blocks.RichTextBlock()),
    ("image", ImageChooserBlock()),
]


# Top-level body. Every entry here corresponds to one branch of the
# serializer's dispatch table.
BODY_BLOCKS = [
    ("heading", HeadingStruct()),
    ("paragraph", blocks.RichTextBlock()),
    ("text", blocks.TextBlock()),
    ("number", blocks.IntegerBlock()),
    ("flag", blocks.BooleanBlock(required=False)),
    ("link", blocks.URLBlock()),
    ("image", ImageChooserBlock()),
    ("document", DocumentChooserBlock()),
    ("page_link", blocks.PageChooserBlock()),
    ("cta", CTAStruct()),
    ("faqs", blocks.ListBlock(FAQItem())),
    ("inner_stream", blocks.StreamBlock(INNER_STREAM_BLOCKS)),
]


class TestStreamPage(Page):
    """Single page model that lights up every serializer code path."""

    body = StreamField(BODY_BLOCKS, use_json_field=True, blank=True)

    api_fields = [
        APIField("body"),
    ]

    class Meta:
        verbose_name = "Test Stream Page"


class TestRenditionPage(Page):
    """Page with an image FK to exercise denormalization through PageSerializer.

    The image FK lets us check that ``_serialize_field`` reaches into
    Wagtail's image model and returns the canonical image dict rather
    than a bare integer pk.
    """

    cover = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    api_fields = [
        APIField("cover"),
    ]

    class Meta:
        verbose_name = "Test Rendition Page"


@register_snippet
class TestAuthor(models.Model):
    """Minimal snippet model used by snippets.* query tests.

    Declared as a snippet via ``register_snippet`` so Wagtail's
    ``get_snippet_models()`` enumerates it. The model shape is kept
    deliberately flat — one CharField plus the implicit pk — because
    the snippets toolset's job is to proxy the model surface, not to
    exercise exotic field types.
    """

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Test Author"


# Suppress an "unused import" lint warning: ImageRenditionField is kept
# in scope so future tests that exercise the rendition-field shape can
# import it from one place. This pattern matches Wagtail's own test apps.
__all__ = [
    "BODY_BLOCKS",
    "CTAStruct",
    "FAQItem",
    "HeadingStruct",
    "INNER_STREAM_BLOCKS",
    "ImageRenditionField",
    "TestAuthor",
    "TestRenditionPage",
    "TestStreamPage",
]
