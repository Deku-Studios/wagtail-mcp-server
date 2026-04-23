"""Media toolset.

Off by default. Manages Wagtail images and documents over MCP:

    media.images.list           List images (filter by collection + tag).
    media.images.get            Full image payload with renditions.
    media.images.get_upload_url
                                Mint a presigned PUT URL + upload token.
    media.images.finalize       Register an uploaded object as a Wagtail Image.
    media.images.update         Update title, alt-text, focal point, tags, collection.
    media.images.focal_point    (v0.5) Narrow focal-point set/clear.

    media.documents.list
    media.documents.get
    media.documents.get_upload_url
    media.documents.finalize
    media.documents.update

Upload flow
-----------
Bytes never touch Django. The agent calls ``get_upload_url``, receives a
presigned PUT URL scoped to a per-upload object key, PUTs the bytes direct
to the S3-compatible bucket (Cloudflare R2 in the Lex deployment), then
calls ``finalize`` with the returned upload token. The toolset
HEAD-checks the object, computes metadata, and creates the Wagtail
``Image`` / ``Document`` row pointing at that key.

This keeps Django off the bytes path, which matters for 25 MB images
over Railway's ephemeral disk.

Gates
-----
Two gates guard every write:

    1. The toolset itself must be enabled (handled at registration).
    2. The user must hold the Wagtail collection-level ``add`` / ``change``
       permission for the target collection.

Uploads do **not** require ``LIMITS.ALLOW_DESTRUCTIVE`` -- creating new
media is recoverable via the normal Wagtail delete flow. Per-upload size
is capped at ``LIMITS.MAX_UPLOAD_MB``.

Storage backend
---------------
Requires ``django-storages`` with an S3-compatible backend as the default
file storage. The toolset refuses to mint presigned URLs if the active
storage does not expose a boto3-style ``connection`` attribute -- this is
a loud failure on purpose, because the alternative is agents silently
failing to upload to the filesystem storage in local dev.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from mcp_server.djangomcp import MCPToolset

from ..settings import get_config

# ------------------------------------------------------------------- constants

# Content-type allow-lists. Anything outside these raises; keeping the
# surface small is how we avoid the agent accidentally uploading a
# user-controlled SVG with embedded script into the image library.
_ALLOWED_IMAGE_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
})

_ALLOWED_DOCUMENT_CONTENT_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/csv",
    "text/plain",
    "text/markdown",
    "application/json",
})

# Signer for upload tokens. The salt is versioned so we can rotate without
# invalidating in-flight uploads silently.
_UPLOAD_TOKEN_SALT = "wagtail_mcp_server.media.upload_token:v1"  # noqa: S105 - signer salt, not a password

# Tokens are issued alongside presigned PUT URLs. The presigned URL TTL
# (5 min) limits how long the agent can upload for; the token max-age
# (10 min) covers the extra slack for network + finalize time.
_PRESIGN_TTL_SECONDS = 300
_TOKEN_MAX_AGE_SECONDS = 600

# Keep filename-derived components safe for S3 keys and URLs.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class MediaToolset(MCPToolset):
    """django-mcp-server toolset for images and documents.

    The caller is resolved from ``self.request.user`` on every call.
    """

    name = "media"
    version = "0.5.0"

    # ============================================================ images

    def media_images_list(
        self,
        *,
        collection_id: int | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """List images, optionally filtered by collection and/or tag."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.images import get_image_model

        Image = get_image_model()
        qs = Image.objects.all().select_related("collection").order_by("-created_at")
        if collection_id is not None:
            qs = qs.filter(collection_id=collection_id)
        if tag:
            qs = qs.filter(tags__name__iexact=tag).distinct()

        return _paginate(qs, page, page_size, serializer=_serialize_image)

    def media_images_get(self, *, id: int) -> dict[str, Any]:
        """Return the full payload for one image."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.images import get_image_model

        Image = get_image_model()
        try:
            image = Image.objects.select_related("collection").get(pk=id)
        except Image.DoesNotExist as exc:
            raise ValueError(f"Image id={id} does not exist.") from exc
        return _serialize_image(image, include_renditions=True)

    def media_images_get_upload_url(
        self,
        *,
        filename: str,
        content_type: str,
        collection_id: int | None = None,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Mint a presigned PUT URL for uploading an image direct to storage.

        The agent PUTs the bytes to ``upload_url`` with the ``Content-Type``
        header set to ``content_type``, then calls
        :meth:`media_images_finalize` with the returned ``upload_token``.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_content_type(content_type, _ALLOWED_IMAGE_CONTENT_TYPES, kind="image")
        max_bytes = _max_upload_bytes()
        _require_size_under_cap(size_bytes, max_bytes)

        from wagtail.images import get_image_model

        Image = get_image_model()
        collection = _resolve_collection(collection_id)
        if not _can_add_to_collection(user, collection, Image):
            raise PermissionDenied(
                "User lacks add permission for the target collection."
            )

        upload_to = _image_upload_to(Image)
        key = _make_object_key(upload_to, filename)
        storage = default_storage
        _require_s3_compatible(storage)
        upload_url = _generate_presigned_put(
            storage,
            key=key,
            content_type=content_type,
            expires_in=_PRESIGN_TTL_SECONDS,
        )
        token = _mint_upload_token(
            user=user,
            key=key,
            content_type=content_type,
            max_size=max_bytes,
            kind="image",
        )
        return {
            "upload_url": upload_url,
            "upload_token": token,
            "key": key,
            "expires_in": _PRESIGN_TTL_SECONDS,
            "max_size_bytes": max_bytes,
            "headers": {"Content-Type": content_type},
        }

    def media_images_finalize(
        self,
        *,
        upload_token: str,
        title: str,
        alt_text: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        focal_point: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Register a direct-to-storage upload as a Wagtail Image."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        payload = _verify_upload_token(
            upload_token, expected_kind="image", user=user
        )
        key = payload["key"]
        content_type = payload["content_type"]
        max_size = int(payload["max_size"])

        storage = default_storage
        _require_s3_compatible(storage)
        size_bytes = _require_object(storage, key=key, max_size=max_size)

        from wagtail.images import get_image_model

        Image = get_image_model()
        collection = _resolve_collection(collection_id)
        if not _can_add_to_collection(user, collection, Image):
            raise PermissionDenied(
                "User lacks add permission for the target collection."
            )

        width, height, sha1 = _read_image_metadata(storage, key=key)

        image_kwargs: dict[str, Any] = {
            "title": title,
            "file": key,
            "file_size": size_bytes,
            "file_hash": sha1,
            "collection": collection,
            "uploaded_by_user": user,
        }
        if width is not None:
            image_kwargs["width"] = width
        if height is not None:
            image_kwargs["height"] = height
        if _image_has_alt_field(Image) and alt_text is not None:
            image_kwargs["alt_text"] = alt_text
        if focal_point:
            _apply_focal_point(image_kwargs, focal_point)

        image = Image.objects.create(**image_kwargs)
        if tags:
            image.tags.add(*tags)
            image.save()

        # If the content_type wasn't JPEG/PNG/GIF/WEBP, PIL may not have
        # been able to read the dimensions; surface that to the agent
        # rather than silently leaving w/h at zero.
        result = _serialize_image(image, include_renditions=True)
        result["content_type"] = content_type
        return result

    def media_images_update(
        self,
        *,
        id: int,
        title: str | None = None,
        alt_text: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        focal_point: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Update image metadata without touching the underlying bytes."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.images import get_image_model

        Image = get_image_model()
        try:
            image = Image.objects.select_related("collection").get(pk=id)
        except Image.DoesNotExist as exc:
            raise ValueError(f"Image id={id} does not exist.") from exc
        if not _can_change_instance(user, image, Image):
            raise PermissionDenied(
                f"User lacks change permission for image {id}."
            )

        if title is not None:
            image.title = title
        if alt_text is not None and _image_has_alt_field(Image):
            image.alt_text = alt_text
        if collection_id is not None:
            new_collection = _resolve_collection(collection_id)
            if not _can_add_to_collection(user, new_collection, Image):
                raise PermissionDenied(
                    "User lacks add permission for the target collection."
                )
            image.collection = new_collection
        if focal_point is not None:
            _apply_focal_point_on_instance(image, focal_point)

        image.save()
        if tags is not None:
            image.tags.set(tags)
            image.save()
        return _serialize_image(image, include_renditions=True)

    def media_images_focal_point(
        self,
        *,
        id: int,
        focal_point: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Set or clear the focal point on an image.

        New in v0.5. A narrow alternative to :meth:`media_images_update`
        that only touches the four ``focal_point_*`` fields. Two reasons
        to ship a separate tool rather than overload the existing update:

        - **Validation.** This tool checks that the supplied coordinates
          fit within the image's known dimensions before saving, so the
          agent gets a clean error rather than a silent off-canvas
          focus rectangle. ``media_images_update`` accepts the same
          dict but does no bounds-checking (it is a "drop in whatever
          you've got" surface).
        - **Clearing.** Passing ``focal_point=None`` (or omitting it)
          clears all four focal_point_* fields. ``media_images_update``
          treats omission as "do not touch", so there is no way to
          clear a focal point through it.

        ``focal_point`` shape: ``{x, y, width, height}`` -- all integers,
        x/y treated as the center of the focus rectangle (Wagtail's
        convention). ``width`` and ``height`` are optional and default
        to ``0`` when omitted.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.images import get_image_model

        Image = get_image_model()
        try:
            image = Image.objects.select_related("collection").get(pk=id)
        except Image.DoesNotExist as exc:
            raise ValueError(f"Image id={id} does not exist.") from exc
        if not _can_change_instance(user, image, Image):
            raise PermissionDenied(
                f"User lacks change permission for image {id}."
            )

        if focal_point:
            _validate_focal_point(focal_point, image)
            _apply_focal_point_on_instance(image, focal_point)
        else:
            # Explicit clear: null all four fields. This is the contract
            # difference from media_images_update -- omitting clears here.
            image.focal_point_x = None
            image.focal_point_y = None
            image.focal_point_width = None
            image.focal_point_height = None

        image.save()
        return _serialize_image(image, include_renditions=True)

    # ============================================================ documents

    def media_documents_list(
        self,
        *,
        collection_id: int | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """List documents, optionally filtered by collection and/or tag."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.documents import get_document_model

        Document = get_document_model()
        qs = Document.objects.all().select_related("collection").order_by("-created_at")
        if collection_id is not None:
            qs = qs.filter(collection_id=collection_id)
        if tag:
            qs = qs.filter(tags__name__iexact=tag).distinct()

        return _paginate(qs, page, page_size, serializer=_serialize_document)

    def media_documents_get(self, *, id: int) -> dict[str, Any]:
        """Return the full payload for one document."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.documents import get_document_model

        Document = get_document_model()
        try:
            document = Document.objects.select_related("collection").get(pk=id)
        except Document.DoesNotExist as exc:
            raise ValueError(f"Document id={id} does not exist.") from exc
        return _serialize_document(document)

    def media_documents_get_upload_url(
        self,
        *,
        filename: str,
        content_type: str,
        collection_id: int | None = None,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Mint a presigned PUT URL for uploading a document direct to storage."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_content_type(
            content_type, _ALLOWED_DOCUMENT_CONTENT_TYPES, kind="document"
        )
        max_bytes = _max_upload_bytes()
        _require_size_under_cap(size_bytes, max_bytes)

        from wagtail.documents import get_document_model

        Document = get_document_model()
        collection = _resolve_collection(collection_id)
        if not _can_add_to_collection(user, collection, Document):
            raise PermissionDenied(
                "User lacks add permission for the target collection."
            )

        upload_to = _document_upload_to(Document)
        key = _make_object_key(upload_to, filename)
        storage = default_storage
        _require_s3_compatible(storage)
        upload_url = _generate_presigned_put(
            storage,
            key=key,
            content_type=content_type,
            expires_in=_PRESIGN_TTL_SECONDS,
        )
        token = _mint_upload_token(
            user=user,
            key=key,
            content_type=content_type,
            max_size=max_bytes,
            kind="document",
        )
        return {
            "upload_url": upload_url,
            "upload_token": token,
            "key": key,
            "expires_in": _PRESIGN_TTL_SECONDS,
            "max_size_bytes": max_bytes,
            "headers": {"Content-Type": content_type},
        }

    def media_documents_finalize(
        self,
        *,
        upload_token: str,
        title: str,
        collection_id: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a direct-to-storage upload as a Wagtail Document."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        payload = _verify_upload_token(
            upload_token, expected_kind="document", user=user
        )
        key = payload["key"]
        content_type = payload["content_type"]
        max_size = int(payload["max_size"])

        storage = default_storage
        _require_s3_compatible(storage)
        size_bytes = _require_object(storage, key=key, max_size=max_size)

        from wagtail.documents import get_document_model

        Document = get_document_model()
        collection = _resolve_collection(collection_id)
        if not _can_add_to_collection(user, collection, Document):
            raise PermissionDenied(
                "User lacks add permission for the target collection."
            )

        document = Document.objects.create(
            title=title,
            file=key,
            file_size=size_bytes,
            file_hash=_hash_storage_object(storage, key=key),
            collection=collection,
            uploaded_by_user=user,
        )
        if tags:
            document.tags.add(*tags)
            document.save()

        result = _serialize_document(document)
        result["content_type"] = content_type
        return result

    def media_documents_update(
        self,
        *,
        id: int,
        title: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update document metadata."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        from wagtail.documents import get_document_model

        Document = get_document_model()
        try:
            document = Document.objects.select_related("collection").get(pk=id)
        except Document.DoesNotExist as exc:
            raise ValueError(f"Document id={id} does not exist.") from exc
        if not _can_change_instance(user, document, Document):
            raise PermissionDenied(
                f"User lacks change permission for document {id}."
            )

        if title is not None:
            document.title = title
        if collection_id is not None:
            new_collection = _resolve_collection(collection_id)
            if not _can_add_to_collection(user, new_collection, Document):
                raise PermissionDenied(
                    "User lacks add permission for the target collection."
                )
            document.collection = new_collection

        document.save()
        if tags is not None:
            document.tags.set(tags)
            document.save()
        return _serialize_document(document)


# ===================================================================== helpers


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Anonymous users cannot call media tools.")


def _max_upload_bytes() -> int:
    mb = int(get_config()["LIMITS"].get("MAX_UPLOAD_MB", 25))
    return mb * 1024 * 1024


def _require_content_type(
    content_type: str, allowed: Iterable[str], *, kind: str
) -> None:
    if content_type not in set(allowed):
        raise ValueError(
            f"content_type={content_type!r} is not permitted for {kind} uploads. "
            f"Allowed: {sorted(allowed)}."
        )


def _require_size_under_cap(size_bytes: int | None, max_bytes: int) -> None:
    if size_bytes is None:
        return
    if size_bytes <= 0:
        raise ValueError("size_bytes must be positive.")
    if size_bytes > max_bytes:
        raise ValueError(
            f"size_bytes={size_bytes} exceeds MAX_UPLOAD_MB cap ({max_bytes} bytes)."
        )


def _resolve_collection(collection_id: int | None) -> Any:
    """Resolve a collection id to a Wagtail Collection, defaulting to root."""
    from wagtail.models import Collection

    if collection_id is None:
        return Collection.get_first_root_node()
    try:
        return Collection.objects.get(pk=collection_id)
    except Collection.DoesNotExist as exc:
        raise ValueError(
            f"Collection id={collection_id} does not exist."
        ) from exc


def _image_upload_to(Image: Any) -> str:  # noqa: N803
    field = Image._meta.get_field("file")
    upload_to = getattr(field, "upload_to", "") or "original_images"
    return upload_to if isinstance(upload_to, str) else "original_images"


def _document_upload_to(Document: Any) -> str:  # noqa: N803
    field = Document._meta.get_field("file")
    upload_to = getattr(field, "upload_to", "") or "documents"
    return upload_to if isinstance(upload_to, str) else "documents"


def _make_object_key(upload_to: str, filename: str) -> str:
    safe_name = _SAFE_FILENAME_RE.sub("-", filename).strip("-") or "file"
    prefix = upload_to.rstrip("/")
    return f"{prefix}/{uuid.uuid4().hex}-{safe_name}"


# ----------------------------------------------------------- token plumbing


def _mint_upload_token(
    *,
    user: Any,
    key: str,
    content_type: str,
    max_size: int,
    kind: str,
) -> str:
    signer = TimestampSigner(salt=_UPLOAD_TOKEN_SALT)
    payload = json.dumps(
        {
            "user_id": user.pk,
            "key": key,
            "content_type": content_type,
            "max_size": max_size,
            "kind": kind,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return signer.sign(payload)


def _verify_upload_token(
    token: str, *, expected_kind: str, user: Any
) -> dict[str, Any]:
    signer = TimestampSigner(salt=_UPLOAD_TOKEN_SALT)
    try:
        raw = signer.unsign(token, max_age=_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise PermissionDenied("Upload token has expired.") from exc
    except BadSignature as exc:
        raise PermissionDenied("Upload token is invalid.") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PermissionDenied("Upload token payload is malformed.") from exc
    if payload.get("kind") != expected_kind:
        raise PermissionDenied(
            f"Upload token is for kind={payload.get('kind')!r}, expected {expected_kind!r}."
        )
    if payload.get("user_id") != user.pk:
        raise PermissionDenied("Upload token was issued for a different user.")
    return payload


# ----------------------------------------------------------- S3 plumbing


def _require_s3_compatible(storage: Any) -> None:
    """Raise unless the storage backend exposes a boto3-style client.

    django-storages' ``S3Storage`` (via django-storages[s3]) exposes
    ``storage.connection`` — a boto3 ``S3.Client``. We depend on that to
    mint presigned PUT URLs and HEAD-check finalized uploads. Filesystem
    storage in local dev lacks this, and we'd rather fail loud than mint
    URLs that point nowhere.
    """
    connection = getattr(storage, "connection", None)
    if connection is None or not hasattr(connection, "generate_presigned_url"):
        raise RuntimeError(
            "media toolset requires an S3-compatible default_storage backend "
            "(e.g. django-storages S3Storage against Cloudflare R2). The active "
            "storage does not expose a boto3-style connection. Configure "
            "CLOUDFLARE_R2_* env vars or keep media.* toolset disabled."
        )


def _generate_presigned_put(
    storage: Any, *, key: str, content_type: str, expires_in: int
) -> str:
    client = storage.connection
    bucket = storage.bucket_name
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
    }
    return client.generate_presigned_url(
        ClientMethod="put_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def _require_object(storage: Any, *, key: str, max_size: int) -> int:
    """HEAD the object and enforce the size cap. Returns bytes on success.

    R2 does not enforce Content-Length against a presigned PUT, so we
    verify size here as defense in depth. If the object is missing, this
    raises -- i.e. the agent claimed to finalize before actually putting.
    """
    client = storage.connection
    bucket = storage.bucket_name
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # botocore.exceptions.ClientError et al.
        raise ValueError(
            f"Upload not found at key={key!r}. PUT the bytes to the presigned URL "
            f"before calling finalize."
        ) from exc
    size = int(head.get("ContentLength", 0))
    if size <= 0:
        raise ValueError(
            f"Upload at key={key!r} has zero bytes; finalize refused."
        )
    if size > max_size:
        raise ValueError(
            f"Upload at key={key!r} is {size} bytes, exceeds cap of {max_size}."
        )
    return size


def _read_image_metadata(
    storage: Any, *, key: str
) -> tuple[int | None, int | None, str]:
    """Return (width, height, sha1-hex) for an image stored at ``key``.

    Width/height come from PIL; for SVG or other vector formats PIL may
    not be able to open the file -- in that case we return ``(None, None)``
    and let Wagtail's storage-side handlers (or the human editor) fill
    them in later.
    """
    from io import BytesIO

    with storage.open(key, "rb") as fh:
        data = fh.read()
    sha1 = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    width: int | None = None
    height: int | None = None
    try:
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(data)) as pil_img:
            width, height = pil_img.size
    except Exception:  # PIL raises many things; swallow for vector/other.
        width, height = None, None
    return width, height, sha1


def _hash_storage_object(storage: Any, *, key: str) -> str:
    """Return a sha1 hex digest of the object stored at ``key``."""
    h = hashlib.sha1(usedforsecurity=False)
    with storage.open(key, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# -------------------------------------------------------- permission helpers


def _can_add_to_collection(user: Any, collection: Any, model: Any) -> bool:
    """Whether ``user`` may add a ``model`` instance to ``collection``."""
    if getattr(user, "is_superuser", False):
        return True
    policy = _permission_policy(model)
    if policy is None:
        # Fall back to model-level add perm if the model lacks a
        # collection-aware permission policy.
        return _has_model_perm(user, model, "add")
    checker = getattr(policy, "user_has_permission_for_instance", None)
    if callable(checker):
        # Wagtail's collection permission policy checks the "add" action
        # against a stub instance bound to ``collection``.
        stub = model(collection=collection)
        return bool(checker(user, "add", stub))
    return _has_model_perm(user, model, "add")


def _can_change_instance(user: Any, instance: Any, model: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    policy = _permission_policy(model)
    if policy is None:
        return _has_model_perm(user, model, "change")
    checker = getattr(policy, "user_has_permission_for_instance", None)
    if callable(checker):
        return bool(checker(user, "change", instance))
    return _has_model_perm(user, model, "change")


def _permission_policy(model: Any) -> Any:
    """Return the Wagtail permission policy for an Image/Document model, if any."""
    # Wagtail attaches ``permission_policy`` at the viewset level, not the
    # model. Look it up via the model's default manager convention.
    try:
        from wagtail.images import get_image_model
        from wagtail.images.permissions import (
            permission_policy as image_policy,
        )

        if model is get_image_model():
            return image_policy
    except Exception:  # noqa: S110, BLE001 - optional wagtail.images may not be installed
        pass
    try:
        from wagtail.documents import get_document_model
        from wagtail.documents.permissions import (
            permission_policy as document_policy,
        )

        if model is get_document_model():
            return document_policy
    except Exception:  # noqa: S110, BLE001 - optional wagtail.documents may not be installed
        pass
    return None


def _has_model_perm(user: Any, model: Any, action: str) -> bool:
    codename = f"{action}_{model._meta.model_name}"
    return bool(user.has_perm(f"{model._meta.app_label}.{codename}"))


# ------------------------------------------------------------- model helpers


def _image_has_alt_field(Image: Any) -> bool:  # noqa: N803
    from django.core.exceptions import FieldDoesNotExist

    try:
        Image._meta.get_field("alt_text")
    except FieldDoesNotExist:
        return False
    return True


def _apply_focal_point(kwargs: dict[str, Any], focal_point: dict[str, int]) -> None:
    for attr in ("focal_point_x", "focal_point_y", "focal_point_width", "focal_point_height"):
        key = attr.replace("focal_point_", "")
        if key in focal_point:
            kwargs[attr] = int(focal_point[key])


def _apply_focal_point_on_instance(
    image: Any, focal_point: dict[str, int]
) -> None:
    for attr in ("focal_point_x", "focal_point_y", "focal_point_width", "focal_point_height"):
        key = attr.replace("focal_point_", "")
        if key in focal_point:
            setattr(image, attr, int(focal_point[key]))


def _validate_focal_point(focal_point: dict[str, int], image: Any) -> None:
    """Reject focal-point payloads that don't fit on the image canvas.

    Used only by :meth:`MediaToolset.media_images_focal_point`; the
    general-purpose ``media_images_update`` is intentionally lenient and
    skips this check.

    - x and y are required and must be non-negative integers.
    - x must lie within ``[0, image.width]`` (when width is known).
    - y must lie within ``[0, image.height]`` (when height is known).
    - width and height are optional but must be non-negative integers
      when provided. Both default to ``0`` if omitted, which means
      "point only, no rect" -- Wagtail handles that fine.

    Vector images (SVG) often have ``width = height = None``; in that
    case bounds-checking is skipped because we have nothing to check
    against. The agent gets the same flexibility a human would.
    """
    if not isinstance(focal_point, dict):
        raise ValueError(
            f"focal_point must be a dict; got {type(focal_point).__name__}."
        )
    for key in ("x", "y"):
        if key not in focal_point:
            raise ValueError(f"focal_point requires '{key}'.")
        value = focal_point[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"focal_point.{key} must be a non-negative integer; got {value!r}."
            )
    for key in ("width", "height"):
        if key in focal_point:
            value = focal_point[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    f"focal_point.{key} must be a non-negative integer; got {value!r}."
                )

    img_width = getattr(image, "width", None)
    img_height = getattr(image, "height", None)
    if img_width and focal_point["x"] > img_width:
        raise ValueError(
            f"focal_point.x={focal_point['x']} exceeds image width {img_width}."
        )
    if img_height and focal_point["y"] > img_height:
        raise ValueError(
            f"focal_point.y={focal_point['y']} exceeds image height {img_height}."
        )


# ---------------------------------------------------------------- paginators


def _paginate(
    qs: Any, page: int, page_size: int | None, *, serializer: Any
) -> dict[str, Any]:
    cfg = get_config()
    default_page_size = int(cfg["LIMITS"].get("MAX_PAGE_SIZE", 50))
    size = int(page_size or default_page_size)
    if size <= 0:
        raise ValueError("page_size must be positive.")
    if page <= 0:
        raise ValueError("page must be positive.")
    offset = (page - 1) * size
    total = qs.count()
    rows = list(qs[offset : offset + size])
    return {
        "total": total,
        "page": page,
        "page_size": size,
        "results": [serializer(row) for row in rows],
    }


# --------------------------------------------------------------- serializers


def _serialize_image(image: Any, *, include_renditions: bool = False) -> dict[str, Any]:
    out = {
        "id": image.pk,
        "title": image.title,
        "filename": _basename(image.file.name if image.file else ""),
        "url": _safe_url(image.file),
        "width": getattr(image, "width", None),
        "height": getattr(image, "height", None),
        "file_size": getattr(image, "file_size", None),
        "collection_id": getattr(image, "collection_id", None),
        "collection_name": (
            getattr(image.collection, "name", None) if image.collection_id else None
        ),
        "tags": [t.name for t in image.tags.all()] if image.pk else [],
        "focal_point": _focal_point(image),
        "alt_text": getattr(image, "alt_text", None),
        "created_at": _iso(getattr(image, "created_at", None)),
    }
    if include_renditions:
        out["renditions"] = _default_renditions(image)
    return out


def _serialize_document(document: Any) -> dict[str, Any]:
    return {
        "id": document.pk,
        "title": document.title,
        "filename": _basename(document.file.name if document.file else ""),
        "url": _safe_url(document.file),
        "file_size": getattr(document, "file_size", None),
        "collection_id": getattr(document, "collection_id", None),
        "collection_name": (
            getattr(document.collection, "name", None)
            if document.collection_id
            else None
        ),
        "tags": [t.name for t in document.tags.all()] if document.pk else [],
        "created_at": _iso(getattr(document, "created_at", None)),
    }


def _safe_url(file_field: Any) -> str | None:
    try:
        return file_field.url if file_field else None
    except Exception:
        return None


def _basename(name: str) -> str:
    if not name:
        return ""
    return name.rsplit("/", 1)[-1]


def _focal_point(image: Any) -> dict[str, int] | None:
    x = getattr(image, "focal_point_x", None)
    y = getattr(image, "focal_point_y", None)
    if x is None or y is None:
        return None
    return {
        "x": x,
        "y": y,
        "width": getattr(image, "focal_point_width", None) or 0,
        "height": getattr(image, "focal_point_height", None) or 0,
    }


def _default_renditions(image: Any) -> list[dict[str, Any]]:
    """Return a small set of pre-baked renditions for convenience.

    Keep this list short; agents that want a specific size can ask for
    it against the REST API. The defaults cover the homepage + social
    card + thumbnail cases the Lex frontends actually consume.
    """
    specs = ["fill-1200x630", "fill-800x600", "fill-400x300"]
    out: list[dict[str, Any]] = []
    for spec in specs:
        try:
            r = image.get_rendition(spec)
        except Exception:  # noqa: S112, BLE001 - skip unrenderable sizes (e.g. SVG)
            continue
        out.append(
            {
                "spec": spec,
                "url": _safe_url(r.file),
                "width": r.width,
                "height": r.height,
            }
        )
    return out


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()
