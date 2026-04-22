"""Wagtail page-reference denormalizer.

Used by the StreamField walker (``PageChooserBlock`` value) to render a
slim preview of a linked page. Distinct from ``page.py``, which builds
the full page payload returned by ``pages.get``.

Read shape::

    {
        "_raw_id": 7,
        "id": 7,
        "title": "Pricing",
        "slug": "pricing",
        "url_path": "/home/pricing/",
        "page_type": "cms.HomePage"
    }

``_raw_id`` is the canonical write key. Everything else is denormalized
read convenience and is ignored on write. We deliberately do not embed
the full page payload here; if the consumer wants more, they call
``pages.get`` with the id.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def serialize_page_ref(page: Any) -> dict[str, Any] | None:
    """Return the canonical denormalized page-reference dict, or ``None``.

    ``page`` is a ``wagtail.models.Page`` instance (or any duck-typed object
    with ``id``, ``title``, ``slug``, and ``url_path``). The ``url_path``
    field is the materialized public path Wagtail computes from the tree
    position; we surface it directly rather than calling ``.url`` since
    ``.url`` requires a request context to resolve site roots reliably.
    """
    if page is None:
        return None

    try:
        page_type = f"{page._meta.app_label}.{page.__class__.__name__}"
    except AttributeError:
        page_type = ""

    return {
        "_raw_id": page.pk,
        "id": page.pk,
        "title": getattr(page, "title", "") or "",
        "slug": getattr(page, "slug", "") or "",
        "url_path": getattr(page, "url_path", "") or "",
        "page_type": page_type,
    }
