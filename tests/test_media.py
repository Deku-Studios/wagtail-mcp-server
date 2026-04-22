"""Tests for ``MediaToolset``.

Coverage map:

    1. Auth gate — anonymous user raises ``PermissionDenied`` on every
       method.
    2. Read path — ``media.images.list`` / ``media.images.get`` work
       against the real fixtures from ``conftest.py``.
    3. Content-type gate — ``get_upload_url`` rejects disallowed types.
    4. S3-compatibility gate — ``get_upload_url`` refuses the default
       filesystem storage (it has no boto3 ``connection``).
    5. Presign happy path — with a fake S3-compatible storage, the agent
       gets back an upload URL and an upload token.
    6. Token round-trip — ``finalize`` verifies the signed token, HEADs
       the fake object, and creates a Wagtail Image row.
    7. Token tampering — a token from another user raises
       ``PermissionDenied``; an ``image`` token cannot finalize a
       document upload.

The S3 backend is not mocked via ``unittest.mock``; instead we monkeypatch
``default_storage`` inside the module under test with a hand-rolled stub
that matches django-storages' ``S3Storage`` surface just enough for the
toolset's needs. This keeps the tests fast and avoids a runtime dep on
``moto`` or a live MinIO.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from django.core.exceptions import PermissionDenied
from django.core.signing import TimestampSigner

from wagtail_mcp_server.toolsets import media as media_module
from wagtail_mcp_server.toolsets.media import MediaToolset


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def toolset():
    return MediaToolset()


@pytest.fixture
def superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        password="x",  # noqa: S106
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="bob",
        password="x",  # noqa: S106
        is_superuser=True,
        is_staff=True,
    )


_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415478da6300010000000500010d0a2db40000000049454e44ae426082"
)


class _FakeS3Client:
    """Just enough of a boto3 S3.Client to satisfy the presign + HEAD flow."""

    def __init__(self, *, objects: dict[str, bytes] | None = None) -> None:
        self._objects = objects if objects is not None else {}

    # ------------ presign ------------
    def generate_presigned_url(
        self, ClientMethod: str, Params: dict, ExpiresIn: int  # noqa: N803
    ) -> str:
        return (
            f"https://fake.r2/{Params['Bucket']}/{Params['Key']}"
            f"?presigned=1&expires={ExpiresIn}"
        )

    # ------------ HEAD ------------
    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if Key not in self._objects:
            raise RuntimeError(f"no such key: {Key}")
        return {"ContentLength": len(self._objects[Key])}


class _FakeS3Storage:
    """Thin stand-in for django-storages' S3Storage.

    The toolset only reaches for ``connection``, ``bucket_name``, and
    ``open(key, 'rb')``. Implementing those three is enough; none of
    Wagtail's image pipeline touches this storage because we bypass
    Django upload and create Image rows with a key already on R2.
    """

    def __init__(self, *, bucket_name: str = "lex-assets") -> None:
        self.bucket_name = bucket_name
        self._objects: dict[str, bytes] = {}
        self.connection = _FakeS3Client(objects=self._objects)

    def put(self, key: str, data: bytes) -> None:
        """Test hook: simulate the agent PUTting bytes direct to R2."""
        self._objects[key] = data

    def open(self, key: str, mode: str = "rb"):  # noqa: ANN202
        if key not in self._objects:
            raise FileNotFoundError(key)
        return BytesIO(self._objects[key])


@pytest.fixture
def fake_s3(monkeypatch) -> _FakeS3Storage:
    """Swap ``default_storage`` inside the media module with a fake S3."""
    storage = _FakeS3Storage()
    monkeypatch.setattr(media_module, "default_storage", storage)
    return storage


# ------------------------------------------------------------------- auth gate


@pytest.mark.django_db
def test_media_list_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.media_images_list(None)


@pytest.mark.django_db
def test_media_get_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.media_images_get(None, id=1)


@pytest.mark.django_db
def test_media_upload_url_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.media_images_get_upload_url(
            None, filename="x.png", content_type="image/png"
        )


@pytest.mark.django_db
def test_media_finalize_rejects_anonymous(toolset):
    with pytest.raises(PermissionDenied):
        toolset.media_images_finalize(None, upload_token="nope", title="x")


# --------------------------------------------------------------------- read path


@pytest.mark.django_db
def test_images_list_returns_paginated_shape(toolset, superuser, image_obj):
    result = toolset.media_images_list(superuser, page_size=10)
    assert result["total"] >= 1
    assert result["page"] == 1
    ids = [r["id"] for r in result["results"]]
    assert image_obj.pk in ids


@pytest.mark.django_db
def test_images_get_returns_full_payload(toolset, superuser, image_obj):
    payload = toolset.media_images_get(superuser, id=image_obj.pk)
    assert payload["id"] == image_obj.pk
    assert payload["title"] == "Cover"
    # Width/height are 1x1 from the tiny PNG fixture.
    assert payload["width"] == 1
    assert payload["height"] == 1
    # include_renditions=True is implicit in .get(); the list of renditions
    # may be empty (renditions depend on image size vs spec) but the key
    # must exist.
    assert "renditions" in payload


@pytest.mark.django_db
def test_images_get_missing_raises(toolset, superuser):
    with pytest.raises(ValueError):
        toolset.media_images_get(superuser, id=999_999)


@pytest.mark.django_db
def test_documents_list_and_get(toolset, superuser, document_obj):
    listed = toolset.media_documents_list(superuser)
    assert listed["total"] >= 1

    payload = toolset.media_documents_get(superuser, id=document_obj.pk)
    assert payload["id"] == document_obj.pk
    assert payload["title"] == "Whitepaper"


# -------------------------------------------------------- content-type gate


@pytest.mark.django_db
def test_upload_url_rejects_disallowed_image_type(toolset, superuser):
    with pytest.raises(ValueError) as excinfo:
        toolset.media_images_get_upload_url(
            superuser,
            filename="payload.exe",
            content_type="application/x-msdownload",
        )
    assert "not permitted" in str(excinfo.value)


@pytest.mark.django_db
def test_upload_url_rejects_oversize_declared(toolset, superuser, fake_s3):
    # 10 GB, way above the 25 MB default cap.
    with pytest.raises(ValueError) as excinfo:
        toolset.media_images_get_upload_url(
            superuser,
            filename="huge.png",
            content_type="image/png",
            size_bytes=10 * 1024 ** 3,
        )
    assert "exceeds" in str(excinfo.value).lower()


# ------------------------------------------------------- S3-compatibility gate


@pytest.mark.django_db
def test_upload_url_refuses_filesystem_storage(toolset, superuser):
    """No boto3 ``connection`` attr -> RuntimeError.

    This is the default pytest storage (FileSystemStorage). The toolset
    fails loud rather than silently mint URLs that point nowhere.
    """
    with pytest.raises(RuntimeError) as excinfo:
        toolset.media_images_get_upload_url(
            superuser, filename="ok.png", content_type="image/png"
        )
    assert "S3-compatible" in str(excinfo.value)


# ---------------------------------------------------------------- presign path


@pytest.mark.django_db
def test_get_upload_url_returns_presigned_and_token(
    toolset, superuser, fake_s3
):
    payload = toolset.media_images_get_upload_url(
        superuser, filename="hero.png", content_type="image/png"
    )
    assert payload["upload_url"].startswith("https://fake.r2/lex-assets/")
    assert "hero.png" in payload["key"]
    assert payload["headers"] == {"Content-Type": "image/png"}
    assert payload["upload_token"]
    assert payload["expires_in"] == 300
    # Max-size is echoed so the agent can surface a friendly error
    # before attempting the PUT.
    assert payload["max_size_bytes"] > 0


@pytest.mark.django_db
def test_get_upload_url_sanitizes_filename(toolset, superuser, fake_s3):
    payload = toolset.media_images_get_upload_url(
        superuser,
        filename="../../etc/passwd?evil=1.png",
        content_type="image/png",
    )
    # The key is structured as ``<upload_to>/<uuid>-<safe_name>``. The
    # upload_to prefix is the one-and-only ``/`` we expect; the dangerous
    # path separators and querystring characters in the user-supplied
    # filename must be scrubbed. ``..`` itself is allowed — S3 keys are
    # opaque strings, not filesystem paths.
    _, _, safe_name_part = payload["key"].partition("/")
    assert "/" not in safe_name_part
    assert "?" not in safe_name_part
    assert "=" not in safe_name_part
    # The key still ends with the original extension so S3 object metadata
    # can surface the MIME type for direct downloads.
    assert payload["key"].endswith(".png")


# ---------------------------------------------------------------- finalize


@pytest.mark.django_db
def test_finalize_creates_wagtail_image(toolset, superuser, fake_s3):
    presign = toolset.media_images_get_upload_url(
        superuser, filename="final.png", content_type="image/png"
    )
    # Simulate the agent uploading bytes direct to R2.
    fake_s3.put(presign["key"], _TINY_PNG)

    payload = toolset.media_images_finalize(
        superuser,
        upload_token=presign["upload_token"],
        title="Final image",
        alt_text="A tiny PNG",
        tags=["hero", "landing"],
    )
    assert payload["title"] == "Final image"
    assert set(payload["tags"]) == {"hero", "landing"}
    # file_size reflects the HEAD ContentLength; width/height come from
    # PIL parsing the stored bytes.
    assert payload["file_size"] == len(_TINY_PNG)
    assert payload["width"] == 1
    assert payload["height"] == 1
    assert payload["content_type"] == "image/png"

    # Verify the Image row actually landed in the DB.
    from wagtail.images import get_image_model

    Image = get_image_model()
    assert Image.objects.filter(pk=payload["id"]).exists()


@pytest.mark.django_db
def test_finalize_before_put_raises(toolset, superuser, fake_s3):
    """Agent calls finalize before uploading -> ValueError, no row created."""
    presign = toolset.media_images_get_upload_url(
        superuser, filename="missing.png", content_type="image/png"
    )
    with pytest.raises(ValueError) as excinfo:
        toolset.media_images_finalize(
            superuser,
            upload_token=presign["upload_token"],
            title="Never uploaded",
        )
    # Message must hint at the cause so agents don't chase their tail.
    assert "PUT" in str(excinfo.value) or "not found" in str(excinfo.value).lower()


# --------------------------------------------------------- token tampering


@pytest.mark.django_db
def test_finalize_rejects_token_from_another_user(
    toolset, superuser, other_user, fake_s3
):
    presign = toolset.media_images_get_upload_url(
        superuser, filename="stolen.png", content_type="image/png"
    )
    fake_s3.put(presign["key"], _TINY_PNG)
    with pytest.raises(PermissionDenied):
        toolset.media_images_finalize(
            other_user,
            upload_token=presign["upload_token"],
            title="Not yours",
        )


@pytest.mark.django_db
def test_finalize_rejects_image_token_for_document(
    toolset, superuser, fake_s3
):
    """An image upload token cannot finalize a document (kind mismatch)."""
    presign = toolset.media_images_get_upload_url(
        superuser, filename="mismatch.png", content_type="image/png"
    )
    fake_s3.put(presign["key"], _TINY_PNG)
    with pytest.raises(PermissionDenied):
        toolset.media_documents_finalize(
            superuser,
            upload_token=presign["upload_token"],
            title="Wrong kind",
        )


@pytest.mark.django_db
def test_finalize_rejects_tampered_token(toolset, superuser, fake_s3):
    presign = toolset.media_images_get_upload_url(
        superuser, filename="tampered.png", content_type="image/png"
    )
    fake_s3.put(presign["key"], _TINY_PNG)
    # Flip a character near the signature end — unsign() will reject.
    bad = presign["upload_token"][:-1] + (
        "A" if presign["upload_token"][-1] != "A" else "B"
    )
    with pytest.raises(PermissionDenied):
        toolset.media_images_finalize(
            superuser, upload_token=bad, title="Tampered"
        )


@pytest.mark.django_db
def test_finalize_rejects_unsigned_token(toolset, superuser, fake_s3):
    """A raw (non-signed) string is rejected with a clear PermissionDenied."""
    with pytest.raises(PermissionDenied):
        toolset.media_images_finalize(
            superuser, upload_token="not.a.signed.token", title="Bogus"
        )


# ------------------------------------------------------- documents happy path


@pytest.mark.django_db
def test_documents_upload_and_finalize(toolset, superuser, fake_s3):
    presign = toolset.media_documents_get_upload_url(
        superuser, filename="spec.pdf", content_type="application/pdf"
    )
    payload_bytes = b"%PDF-1.4 fake"
    fake_s3.put(presign["key"], payload_bytes)

    payload = toolset.media_documents_finalize(
        superuser,
        upload_token=presign["upload_token"],
        title="Spec",
        tags=["internal"],
    )
    assert payload["title"] == "Spec"
    assert payload["file_size"] == len(payload_bytes)
    assert set(payload["tags"]) == {"internal"}

    from wagtail.documents import get_document_model

    Document = get_document_model()
    assert Document.objects.filter(pk=payload["id"]).exists()


# ----------------------------------------------------------- update handlers


@pytest.mark.django_db
def test_update_image_title_and_tags(toolset, superuser, image_obj):
    updated = toolset.media_images_update(
        superuser, id=image_obj.pk, title="Renamed", tags=["fresh"]
    )
    assert updated["title"] == "Renamed"
    assert updated["tags"] == ["fresh"]


@pytest.mark.django_db
def test_update_image_missing_raises(toolset, superuser):
    with pytest.raises(ValueError):
        toolset.media_images_update(superuser, id=999_999, title="nope")


# ------------------------------------------------------ signed-token sanity


def test_token_payload_is_json_with_expected_keys(monkeypatch):
    """The token carries enough for finalize to replay its checks.

    This is a contract test — the payload shape must stay stable across
    releases, otherwise existing in-flight uploads break on upgrade.
    """
    from wagtail_mcp_server.toolsets.media import (
        _UPLOAD_TOKEN_SALT,
        _mint_upload_token,
    )

    class _Stub:
        pk = 42

    token = _mint_upload_token(
        user=_Stub(),
        key="original_images/abc-def.png",
        content_type="image/png",
        max_size=1024,
        kind="image",
    )
    import json

    signer = TimestampSigner(salt=_UPLOAD_TOKEN_SALT)
    raw = signer.unsign(token, max_age=600)
    payload = json.loads(raw)
    assert payload == {
        "user_id": 42,
        "key": "original_images/abc-def.png",
        "content_type": "image/png",
        "max_size": 1024,
        "kind": "image",
    }


# --------------------------------------------------- image fixture sanity


def test_tiny_png_fixture_shape():
    """Guard against fixture drift: the tiny PNG bytes must decode to a 1x1 PNG.

    If this fails, the ``finalize`` tests' width/height assertions fail
    with a much uglier error; keeping the check here surfaces the cause.
    """
    from PIL import Image as PILImage

    with PILImage.open(BytesIO(_TINY_PNG)) as img:
        assert img.size == (1, 1)
    # sha1 round-trips to a stable 40-char hex digest.
    assert len(hashlib.sha1(_TINY_PNG).hexdigest()) == 40
