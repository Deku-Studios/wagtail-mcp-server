"""Tests for ``PageSerializer`` -- the full ``pages.get`` payload."""

from __future__ import annotations

import pytest

from wagtail_mcp_server.serializers.page import PageSerializer


@pytest.mark.django_db
def test_top_level_keys_present(stream_page):
    payload = PageSerializer().serialize(stream_page)
    assert payload["id"] == stream_page.pk
    assert payload["type"].endswith(".TestStreamPage")
    assert payload["title"] == "Stream"
    assert payload["slug"] == "stream"
    assert payload["url_path"].endswith("/stream/")


@pytest.mark.django_db
def test_meta_block_includes_publication_state(stream_page):
    stream_page.save_revision().publish()
    stream_page.refresh_from_db()
    payload = PageSerializer().serialize(stream_page)
    meta = payload["meta"]
    assert meta["live"] is True
    assert meta["first_published_at"] is not None
    assert "parent" in meta
    assert meta["parent"]["slug"] == "test-home"


@pytest.mark.django_db
def test_fields_honors_api_fields_allowlist(stream_page):
    """Only the fields named in ``api_fields`` should appear under ``fields``."""
    payload = PageSerializer().serialize(stream_page)
    assert set(payload["fields"].keys()) == {"body"}


@pytest.mark.django_db
def test_streamfield_renders_through_walker(stream_page):
    stream_page.body = [("paragraph", "<p>Hi</p>")]
    stream_page.save_revision().publish()
    stream_page.refresh_from_db()
    payload = PageSerializer().serialize(stream_page)
    body = payload["fields"]["body"]
    assert isinstance(body, list)
    assert body[0]["type"] == "paragraph"
    assert "<p>" in body[0]["value"]


@pytest.mark.django_db
def test_image_fk_denormalizes_through_serializer(home_page, image_obj):
    """A model FK to a Wagtail Image should produce the canonical image dict."""
    from tests.testapp.models import TestRenditionPage

    page = TestRenditionPage(title="Rendition", slug="rendition", cover=image_obj)
    home_page.add_child(instance=page)
    page.refresh_from_db()

    payload = PageSerializer().serialize(page)
    cover = payload["fields"]["cover"]
    assert cover["_raw_id"] == image_obj.pk
    assert cover["title"] == "Cover"


@pytest.mark.django_db
def test_subclass_can_override_field_with_serialize_method(stream_page):
    """``serialize_<field>`` overrides the default field rendering."""

    class CustomSerializer(PageSerializer):
        def serialize_body(self, page):  # noqa: ARG002 -- signature contract
            return "stubbed"

    payload = CustomSerializer().serialize(stream_page)
    assert payload["fields"]["body"] == "stubbed"


@pytest.mark.django_db
def test_subclass_extra_fields_are_added(stream_page):
    """``extra_fields`` adds fields beyond the model's ``api_fields``."""

    class WithSlugAlias(PageSerializer):
        extra_fields = ["depth"]

    payload = WithSlugAlias().serialize(stream_page)
    assert "depth" in payload["fields"]
    assert payload["fields"]["depth"] == stream_page.depth
