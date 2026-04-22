"""Wagtail document denormalizer.

Used by the StreamField walker (``DocumentChooserBlock`` value) and by
the ``media.documents.*`` toolset (when it ships in v0.2). Centralized
so the two surfaces emit the identical shape.

Read shape::

    {
        "_raw_id": 17,
        "id": 17,
        "title": "Whitepaper",
        "url": "/documents/17/whitepaper.pdf"
    }

``_raw_id`` is the canonical write key. Title and URL are denormalized
read convenience and are ignored on write. Documents have no
width/height/alt (those are image concerns) and no rendition pipeline,
so this serializer is intentionally smaller than ``image.py``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def serialize_document(document: Any) -> dict[str, Any] | None:
    """Return the canonical denormalized document dict, or ``None`` if falsy.

    ``document`` is a ``wagtail.documents.models.AbstractDocument`` instance
    (or any duck-typed object with ``id``, ``title``, and a ``file`` attribute
    that exposes ``.url``). Storage failures degrade to an empty URL rather
    than raising; the goal is read-path resilience so a single broken upload
    does not nuke an entire ``pages.get`` response.
    """
    if document is None:
        return None

    return {
        "_raw_id": document.pk,
        "id": document.pk,
        "title": getattr(document, "title", "") or "",
        "url": _safe_file_url(document),
    }


def _safe_file_url(document: Any) -> str:
    file_attr = getattr(document, "file", None)
    if file_attr is None:
        return ""
    try:
        return file_attr.url
    except (ValueError, AttributeError):
        # Storage backend can raise ValueError on a missing file; we do not
        # want a single broken upload to break a `pages.get` response.
        logger.warning(
            "wagtail_mcp_server: document file url failed for id=%s",
            getattr(document, "pk", "?"),
            exc_info=True,
        )
        return ""
