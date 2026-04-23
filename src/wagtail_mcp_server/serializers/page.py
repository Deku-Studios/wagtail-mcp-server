"""Page serializer for the read path.

Returns the canonical ``pages.get`` payload. Hosts override per-type by
subclassing :class:`PageSerializer` and registering it (registry hookup
lands when ``PAGE_SERIALIZERS`` config is wired in v0.2; v0.1 uses the
default for every page type).

Read shape::

    {
        "id": 7,
        "type": "cms.HomePage",
        "title": "Home",
        "slug": "home",
        "url_path": "/home/",
        "meta": {
            "live": true,
            "has_unpublished_changes": false,
            "first_published_at": "2026-04-01T00:00:00Z",
            "last_published_at": "2026-04-15T00:00:00Z",
            "parent": {<page_ref> | null},
            "locale": "en"
        },
        "fields": {
            "hero_headline": "Welcome",
            "body": [<envelope>, ...],
            "og_image": {<image_dict>}
        }
    }

The ``fields`` block is driven by the page model's ``api_fields`` list
(Wagtail convention) plus the subclass's ``extra_fields``. Anything not
in either list is omitted; that mirrors how the Wagtail REST API behaves
and makes the read shape predictable.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from .document import serialize_document
from .image import serialize_image
from .page_ref import serialize_page_ref
from .streamfield import SerializeOptions, serialize_streamfield

logger = logging.getLogger(__name__)


# Fields surfaced under ``meta`` on every page payload. Kept small and
# stable so that consumers can rely on the shape without consulting the
# api_fields of every page type.
META_FIELDS: tuple[str, ...] = (
    "live",
    "has_unpublished_changes",
    "first_published_at",
    "last_published_at",
    "locale",
)


class PageSerializer:
    """Convert a Wagtail ``Page`` instance into the read shape above.

    Subclasses customize per-page-type rendering by:

    - Setting ``extra_fields`` to add fields beyond the model's ``api_fields``.
    - Defining ``serialize_<field>(page)`` methods to override the default
      rendering for a specific field. The method should return any
      JSON-friendly value.
    """

    extra_fields: ClassVar[list[str]] = []

    def __init__(self, *, options: SerializeOptions | None = None) -> None:
        self.options = options or SerializeOptions()

    # ------------------------------------------------------------------ public

    def serialize(self, page: Any) -> dict[str, Any]:
        """Return the full read payload for ``page``."""
        return {
            "id": page.pk,
            "type": _page_type_name(page),
            "title": getattr(page, "title", "") or "",
            "slug": getattr(page, "slug", "") or "",
            "url_path": getattr(page, "url_path", "") or "",
            "meta": self._serialize_meta(page),
            "fields": self._serialize_fields(page),
        }

    # ----------------------------------------------------------------- private

    def _serialize_meta(self, page: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for field_name in META_FIELDS:
            value = getattr(page, field_name, None)
            meta[field_name] = _to_json_safe(value)
        parent = page.get_parent() if hasattr(page, "get_parent") else None
        meta["parent"] = serialize_page_ref(parent) if parent else None
        return meta

    def _serialize_fields(self, page: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for field_name in self._field_names(page):
            override = getattr(self, f"serialize_{field_name}", None)
            if callable(override):
                try:
                    out[field_name] = override(page)
                except Exception:  # noqa: BLE001 -- read-path resilience
                    logger.warning(
                        "wagtail_mcp_server: serialize_%s override failed for page id=%s",
                        field_name,
                        page.pk,
                        exc_info=True,
                    )
                    out[field_name] = None
                continue
            out[field_name] = self._serialize_field(page, field_name)
        return out

    def _field_names(self, page: Any) -> list[str]:
        """Allowlist of field names to surface, drawn from api_fields + extras."""
        api_fields = getattr(page, "api_fields", None) or []
        names: list[str] = []
        for entry in api_fields:
            # ``api_fields`` entries are either strings or
            # ``wagtail.api.v2.serializers.APIField`` instances. Both expose
            # ``name`` (the latter as an attribute, the former trivially).
            if isinstance(entry, str):
                names.append(entry)
            else:
                name = getattr(entry, "name", None)
                if name:
                    names.append(name)
        for name in self.extra_fields:
            if name not in names:
                names.append(name)
        return names

    def _serialize_field(self, page: Any, field_name: str) -> Any:
        """Default field rendering, dispatched on the underlying Django field."""
        # Local import keeps this module importable without Wagtail loaded.
        from wagtail.fields import StreamField

        try:
            field = page._meta.get_field(field_name)
        except Exception:  # noqa: BLE001 -- field may be a property/method
            field = None

        # Resolve the value first via attribute access. For api_fields that
        # point at properties or methods (e.g. ``featured_image_url``),
        # ``_meta.get_field`` raises and we fall back to attribute lookup.
        value = getattr(page, field_name, None)
        if callable(value) and not hasattr(value, "_meta"):
            # Methods exposed via api_fields conventionally take no args.
            try:
                value = value()
            except TypeError:
                value = None

        if isinstance(field, StreamField):
            return serialize_streamfield(value, options=self.options)

        # ForeignKey to wagtail Image/Document/Page -> denormalize.
        if value is not None and hasattr(value, "_meta"):
            denormalized = _denormalize_related(value)
            if denormalized is not None:
                return denormalized

        return _to_json_safe(value)


# --------------------------------------------------------------------------- helpers


def _page_type_name(page: Any) -> str:
    """Return ``"<app_label>.<ClassName>"`` for a page instance."""
    try:
        return f"{page._meta.app_label}.{page.__class__.__name__}"
    except AttributeError:
        return ""


def _denormalize_related(obj: Any) -> dict[str, Any] | None:
    """If ``obj`` is a Wagtail Image/Document/Page, return its dict shape."""
    # Local imports to avoid hard-failing if wagtail.images / wagtail.documents
    # are absent in some downstream install.
    try:
        from wagtail.images import get_image_model
        from wagtail.models import Page
    except ImportError:  # pragma: no cover -- wagtail is a hard dep, but defend anyway
        return None
    try:
        from wagtail.documents import get_document_model
    except ImportError:  # pragma: no cover
        get_document_model = None  # type: ignore[assignment]

    image_model = get_image_model()
    if isinstance(obj, image_model):
        return serialize_image(obj)

    if get_document_model is not None:
        document_model = get_document_model()
        if isinstance(obj, document_model):
            return serialize_document(obj)

    if isinstance(obj, Page):
        return serialize_page_ref(obj)

    return None


def _to_json_safe(value: Any) -> Any:
    """Coerce datetimes and other common non-JSON types to JSON-friendly forms.

    Handles:

    - ``datetime`` / ``date`` → ISO-8601 string via ``.isoformat()``.
    - ``wagtail.models.Locale`` → the ``language_code`` string (e.g. ``"en"``).
      This is what every ``pages.get`` payload needs under ``meta.locale`` and
      is the useful shape for agents; the opaque numeric Locale pk is not.

    Anything else is returned unchanged. The JSON encoder further down the
    stack will raise if it still cannot serialize the value; that is the
    correct behavior for truly unknown types (loud failure beats silent
    shape drift).
    """
    import datetime

    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()

    # Locale: import locally so the serializer module stays importable
    # without Wagtail loaded (e.g. during type-stub generation). On the
    # happy path Wagtail is always present so the import is cheap.
    try:
        from wagtail.models import Locale
    except ImportError:  # pragma: no cover -- wagtail is a hard dep
        Locale = None  # type: ignore[assignment]
    if Locale is not None and isinstance(value, Locale):
        return value.language_code

    return value
