"""Shared pytest fixtures for the wagtail-mcp-server test suite."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.images import ImageFile

# A 1x1 PNG byte sequence -- enough for Wagtail's image pipeline to
# accept and not so much that test runs balloon.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415478da6300010000000500010d0a2db40000000049454e44ae426082"
)


@pytest.fixture
def site_root(db):
    """Return the root page Wagtail's migrations create at id=1."""
    from wagtail.models import Page

    return Page.objects.get(pk=1)


@pytest.fixture
def home_page(db, site_root):
    """A bare ``Page`` placed under the root, used as a parent for tests.

    Uses slug ``test-home`` instead of ``home`` because wagtailcore's
    migrations seed a default page at slug ``home`` and we do not want
    a collision when tests run against a freshly migrated database.
    """
    from wagtail.models import Page

    home = Page(title="Test Home", slug="test-home")
    site_root.add_child(instance=home)
    return Page.objects.get(pk=home.pk)


@pytest.fixture
def stream_page(db, home_page):
    """``TestStreamPage`` instance with an empty body, ready to populate per-test."""
    from tests.testapp.models import TestStreamPage

    page = TestStreamPage(title="Stream", slug="stream", body=[])
    home_page.add_child(instance=page)
    return TestStreamPage.objects.get(pk=page.pk)


@pytest.fixture
def image_obj(db):
    """A minimal Wagtail image record backed by a 1x1 PNG."""
    from wagtail.images import get_image_model

    Image = get_image_model()
    img = Image(title="Cover")
    img.file.save("tiny.png", ImageFile(BytesIO(_TINY_PNG), name="tiny.png"))
    img.save()
    return img


@pytest.fixture
def document_obj(db):
    """A minimal Wagtail document record."""
    from django.core.files.base import ContentFile
    from wagtail.documents import get_document_model

    Document = get_document_model()
    doc = Document(title="Whitepaper")
    doc.file.save("whitepaper.pdf", ContentFile(b"%PDF-1.4 stub"))
    doc.save()
    return doc


@pytest.fixture
def staff_user(db):
    """An authenticated, staff-level user for permission-scoped queries."""
    User = get_user_model()
    return User.objects.create_user(
        username="staff",
        password="x",  # noqa: S106
        is_staff=True,
    )
