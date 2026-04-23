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


@pytest.mark.django_db
def test_meta_locale_is_language_code_string(stream_page):
    """Regression: ``meta.locale`` must be the ``language_code`` string, not
    a raw ``wagtail.models.Locale`` instance.

    Prior to 0.5.1, ``_serialize_meta`` passed the FK value through
    ``_to_json_safe`` which only handled datetimes, leaving the Locale
    object unchanged. The MCP JSON encoder then failed with
    ``Unable to serialize unknown type: <class 'wagtail.models.i18n.Locale'>``,
    breaking ``pages.get`` for every page (every page carries a locale).
    """
    import json

    payload = PageSerializer().serialize(stream_page)
    locale_value = payload["meta"]["locale"]
    assert isinstance(locale_value, str)
    assert locale_value == stream_page.locale.language_code
    # Round-trip through json.dumps to guarantee the full payload is
    # JSON-safe -- the actual failure mode on prod was encoder-level.
    json.dumps(payload)
