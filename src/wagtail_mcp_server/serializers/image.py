"""Wagtail image denormalizer.

Used by the StreamField walker (``ImageChooserBlock`` value) and by the
``media.images.*`` toolset (when it ships in v0.2). Centralized so the
two surfaces emit the identical shape.

Read shape::

    {
        "_raw_id": 42,
        "id": 42,
        "title": "Cover image",
        "url": "/media/images/cover.jpg",
        "alt_text": "Robot reading a book",
        "width": 1600,
        "height": 900,
        "rendition_urls": {
            "fill-1200x630": "/media/images/cover.fill-1200x630.jpg"
        }
    }

``_raw_id`` is the canonical write key. Everything else is denormalized
read convenience and is ignored on write.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default rendition the spec calls out (Open Graph 1.91:1). Hosts can
# extend by passing extra rendition specs into ``serialize_image``. The
# library does not auto-render every rendition the host has ever defined
# because that would force a wagtailimages.Rendition write per call.
DEFAULT_RENDITIONS: tuple[str, ...] = ("fill-1200x630",)


def serialize_image(
    image: Any,
    *,
    renditions: tuple[str, ...] = DEFAULT_RENDITIONS,
    include_renditions: bool = True,
) -> dict[str, Any] | None:
    """Return the canonical denormalized image dict, or ``None`` if image is falsy.

    ``image`` is a ``wagtail.images.models.AbstractImage`` instance (or any
    duck-typed object with ``id``, ``title``, ``file``, ``width``, ``height``,
    and a ``get_rendition(spec)`` method). Render failures degrade to an
    omitted rendition entry rather than raising; the goal is read-path
    resilience so a single broken rendition does not nuke an entire
    ``pages.get`` response.
    """
    if image is None:
        return None

    out: dict[str, Any] = {
        "_raw_id": image.pk,
        "id": image.pk,
        "title": getattr(image, "title", "") or "",
        "url": _safe_file_url(image),
        # ``default_alt_text`` is Wagtail 5+'s preferred field name; older
        # apps stash alt text on title. We surface what we can and let the
        # block-level alt override (configured per-placement) win on the
        # consuming side.
        "alt_text": getattr(image, "default_alt_text", "") or "",
        "width": getattr(image, "width", None),
        "height": getattr(image, "height", None),
    }

    if include_renditions:
        out["rendition_urls"] = _safe_renditions(image, renditions)

    return out


def _safe_file_url(image: Any) -> str:
    file_attr = getattr(image, "file", None)
    if file_attr is None:
        return ""
    try:
        return file_attr.url
    except (ValueError, AttributeError):
        # Storage backend can raise ValueError on a missing file; we do not
        # want a single broken upload to break a `pages.get` response.
        return ""


def _safe_renditions(image: Any, specs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not specs:
        return out
    get_rendition = getattr(image, "get_rendition", None)
    if not callable(get_rendition):
        return out
    for spec in specs:
        try:
            rendition = get_rendition(spec)
            out[spec] = rendition.url
        except Exception:  # noqa: BLE001 -- read-path resilience, see module docstring
            logger.warning(
                "wagtail_mcp_server: rendition %r failed for image id=%s",
                spec,
                getattr(image, "pk", "?"),
                exc_info=True,
            )
    return out
