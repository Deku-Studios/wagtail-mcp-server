"""Media toolset.

Off by default. Manages images and documents:

    media.images.list         List images, filterable by collection + tag.
    media.images.get          Full image payload with renditions.
    media.images.upload       Upload a new image (base64 or URL).
    media.images.update       Update metadata (title, alt, tags, collection).
    media.documents.list      Same pattern for documents.
    media.documents.get
    media.documents.upload
    media.documents.update

Uploads are capped at ``LIMITS.MAX_UPLOAD_MB``. Hard deletes are gated
behind ``LIMITS.ALLOW_DESTRUCTIVE``.

Lands in v0.2.
"""

from __future__ import annotations


class MediaToolset:
    """django-mcp-server toolset for images and documents."""

    name = "media"
    version = "0.1.0"
