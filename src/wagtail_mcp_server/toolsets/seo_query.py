"""Read-only SEO toolset.

On by default (safe read). Ships three tools:

    seo.get      SEO fields + audit findings for a single page.
    seo.audit    Site-wide scan; returns pages that have findings.
    seo.sitemap  Parsed sitemap-style list of live URLs.

``SEOWriteToolset`` (off by default) handles mutating SEO fields.

Audit rules
===========

The toolset ships a set of pragmatic, industry-standard rules keyed to
the fields Wagtail gives every ``Page`` out of the box plus an optional
``og_image`` chooser field that most production page models add:

    title_missing          seo_title AND title empty                  error
    title_too_short        computed title < 30 chars                  warn
    title_too_long         computed title > 60 chars                  warn
    description_missing    search_description empty                   warn
    description_too_short  search_description < 70 chars              info
    description_too_long   search_description > 160 chars             warn
    og_image_missing       page has og_image field but it is None     info

Per :attr:`RULES` severities are stable; downstream tools (lex-admin UI,
CI checks) use ``(code, severity)`` as a contract.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_server.djangomcp import MCPToolset

from ..serializers.image import serialize_image
from ..serializers.page_ref import serialize_page_ref

# ---------------------------------------------------------------------------
# Audit rule constants. Exposed as class-level so other callers can read the
# ranges without re-deriving them (e.g. an admin UI that renders a hint).
# ---------------------------------------------------------------------------

TITLE_MIN = 30
TITLE_MAX = 60
DESCRIPTION_MIN = 70
DESCRIPTION_MAX = 160

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"


class SEOQueryToolset(MCPToolset):
    """django-mcp-server toolset for SEO reads.

    The caller is resolved from ``self.request.user`` on every call.
    """

    name = "seo_query"
    version = "0.4.0"

    #: Canonical rule ``(code, severity)`` pairs. Stable contract.
    RULES: ClassVar[dict[str, str]] = {
        "title_missing": SEVERITY_ERROR,
        "title_too_short": SEVERITY_WARN,
        "title_too_long": SEVERITY_WARN,
        "description_missing": SEVERITY_WARN,
        "description_too_short": SEVERITY_INFO,
        "description_too_long": SEVERITY_WARN,
        "og_image_missing": SEVERITY_INFO,
    }

    # ------------------------------------------------------------------ seo.get

    def seo_get(
        self,
        *,
        id: int | None = None,
        slug: str | None = None,
        url_path: str | None = None,
    ) -> dict[str, Any] | None:
        """Return SEO fields + audit findings for one page.

        Exactly one of ``id``, ``slug``, ``url_path`` must be provided.
        Returns ``None`` if the page does not exist or is not visible to
        the authenticated caller.
        """
        if id is None and slug is None and url_path is None:
            raise ValueError("seo.get requires one of: id, slug, url_path")

        user = getattr(self.request, "user", None)
        page = self._find_page(user, id=id, slug=slug, url_path=url_path)
        if page is None:
            return None
        return _seo_payload(page)

    # ---------------------------------------------------------------- seo.audit

    def seo_audit(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        min_severity: str | None = None,
        type: str | None = None,
    ) -> dict[str, Any]:
        """Walk every page the caller can see, returning those with findings.

        ``min_severity`` filters findings at or above the given severity
        (``"info" < "warn" < "error"``). ``type`` restricts the scan to a
        single ``app_label.ClassName``.
        """
        user = getattr(self.request, "user", None)
        qs = self._scoped_queryset(user).live()
        if type:
            model = _resolve_page_model(type)
            if model is None:
                return {"items": [], "total": 0, "limit": 0, "offset": 0}
            qs = qs.type(model)

        limit = max(0, min(int(limit), 500))
        threshold = _severity_rank(min_severity) if min_severity else None

        items: list[dict[str, Any]] = []
        for page in qs.order_by("path"):
            findings = _audit_page(page.specific)
            if threshold is not None:
                findings = [
                    f for f in findings if _severity_rank(f["severity"]) >= threshold
                ]
            if findings:
                items.append(
                    {
                        "page": serialize_page_ref(page.specific),
                        "findings": findings,
                    }
                )

        total = len(items)
        window = items[offset : offset + limit]
        return {
            "items": window,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # -------------------------------------------------------------- seo.sitemap

    def seo_sitemap(
        self,
        *,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return a sitemap-style list of live URLs visible to the caller.

        Intentionally lightweight: deliberately does not reach for
        ``wagtail.contrib.sitemaps`` so the toolset is usable on projects
        that have not installed that contrib app. Each item carries
        ``loc``, ``lastmod`` (``last_published_at``), and a ``page``
        reference for drill-down.
        """
        user = getattr(self.request, "user", None)
        limit = max(0, min(int(limit), 10_000))
        qs = self._scoped_queryset(user).live().order_by("path")[:limit]

        items: list[dict[str, Any]] = []
        for page in qs:
            specific = page.specific
            url = _full_url(specific)
            if not url:
                # Pages without a resolvable full URL are skipped. A page
                # with no Site record attached would be one such case.
                continue
            items.append(
                {
                    "loc": url,
                    "lastmod": _iso(getattr(specific, "last_published_at", None)),
                    "page": serialize_page_ref(specific),
                }
            )
        return {"items": items, "total": len(items)}

    # ---------------------------------------------------------------- internal

    def _find_page(
        self,
        user: Any,
        *,
        id: int | None,
        slug: str | None,
        url_path: str | None,
    ) -> Any | None:
        qs = self._scoped_queryset(user)
        if id is not None:
            qs = qs.filter(pk=id)
        if slug is not None:
            qs = qs.filter(slug=slug)
        if url_path is not None:
            qs = qs.filter(url_path=url_path)
        page = qs.first()
        return page.specific if page else None

    def _scoped_queryset(self, user: Any) -> Any:
        """Pages visible to ``user``; anonymous users see live only.

        Mirrors :class:`PageQueryToolset._scoped_queryset` so
        ``seo.audit`` and ``pages.list`` see the same world.
        """
        from wagtail.models import Page

        qs = Page.objects.all()
        if user is None or not getattr(user, "is_authenticated", False):
            return qs.live()
        per_user_qs = getattr(user, "get_pages_for_user", None)
        if callable(per_user_qs):
            return qs & per_user_qs()  # type: ignore[operator]
        return qs


# --------------------------------------------------------------------- helpers


def _seo_payload(page: Any) -> dict[str, Any]:
    """Build the ``seo.get`` dict for a single page."""
    effective_title = (getattr(page, "seo_title", "") or "").strip() or (
        getattr(page, "title", "") or ""
    ).strip()
    description = (getattr(page, "search_description", "") or "").strip()
    og_image = getattr(page, "og_image", None)

    payload: dict[str, Any] = {
        "page": serialize_page_ref(page),
        "seo_title": getattr(page, "seo_title", "") or "",
        "effective_title": effective_title,
        "search_description": description,
        "slug": getattr(page, "slug", "") or "",
        "url_path": getattr(page, "url_path", "") or "",
        "canonical_url": _full_url(page),
        "last_published_at": _iso(getattr(page, "last_published_at", None)),
    }
    if _page_has_field(page, "og_image"):
        payload["og_image"] = serialize_image(og_image) if og_image else None
    payload["findings"] = _audit_page(page)
    return payload


def _audit_page(page: Any) -> list[dict[str, Any]]:
    """Apply the rule table to one page. Returns a (possibly empty) list."""
    findings: list[dict[str, Any]] = []

    title = (getattr(page, "seo_title", "") or "").strip() or (
        getattr(page, "title", "") or ""
    ).strip()
    if not title:
        findings.append(
            _finding(
                "title_missing",
                field="seo_title",
                message="Page has no seo_title and no title fallback.",
            )
        )
    else:
        length = len(title)
        if length < TITLE_MIN:
            findings.append(
                _finding(
                    "title_too_short",
                    field="seo_title",
                    message=f"Title is {length} chars; aim for {TITLE_MIN}-{TITLE_MAX}.",
                    value_length=length,
                    recommended_range=[TITLE_MIN, TITLE_MAX],
                )
            )
        elif length > TITLE_MAX:
            findings.append(
                _finding(
                    "title_too_long",
                    field="seo_title",
                    message=f"Title is {length} chars; aim for {TITLE_MIN}-{TITLE_MAX}.",
                    value_length=length,
                    recommended_range=[TITLE_MIN, TITLE_MAX],
                )
            )

    description = (getattr(page, "search_description", "") or "").strip()
    if not description:
        findings.append(
            _finding(
                "description_missing",
                field="search_description",
                message="search_description is empty.",
            )
        )
    else:
        length = len(description)
        if length < DESCRIPTION_MIN:
            findings.append(
                _finding(
                    "description_too_short",
                    field="search_description",
                    message=(
                        f"Description is {length} chars; aim for "
                        f"{DESCRIPTION_MIN}-{DESCRIPTION_MAX}."
                    ),
                    value_length=length,
                    recommended_range=[DESCRIPTION_MIN, DESCRIPTION_MAX],
                )
            )
        elif length > DESCRIPTION_MAX:
            findings.append(
                _finding(
                    "description_too_long",
                    field="search_description",
                    message=(
                        f"Description is {length} chars; aim for "
                        f"{DESCRIPTION_MIN}-{DESCRIPTION_MAX}."
                    ),
                    value_length=length,
                    recommended_range=[DESCRIPTION_MIN, DESCRIPTION_MAX],
                )
            )

    if _page_has_field(page, "og_image") and getattr(page, "og_image", None) is None:
        findings.append(
            _finding(
                "og_image_missing",
                field="og_image",
                message="og_image is unset; social shares fall back to site defaults.",
            )
        )

    return findings


def _finding(code: str, **extra: Any) -> dict[str, Any]:
    severity = SEOQueryToolset.RULES[code]
    out: dict[str, Any] = {"code": code, "severity": severity}
    out.update(extra)
    return out


def _severity_rank(severity: str) -> int:
    """Numeric rank for severity comparisons. Higher = more severe."""
    return {SEVERITY_INFO: 0, SEVERITY_WARN: 1, SEVERITY_ERROR: 2}.get(severity, 0)


def _page_has_field(page: Any, name: str) -> bool:
    """True if ``page`` declares ``name`` on its model (not just inherited attr)."""
    try:
        page._meta.get_field(name)
    except Exception:  # noqa: BLE001 -- Wagtail raises FieldDoesNotExist
        return False
    return True


def _full_url(page: Any) -> str:
    """Safe ``page.get_full_url()``: empty string when no Site is configured."""
    try:
        return page.get_full_url() or ""
    except Exception:  # noqa: BLE001 -- Wagtail raises when Site is missing
        return ""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _resolve_page_model(type_name: str) -> Any | None:
    from django.apps import apps

    try:
        app_label, model_name = type_name.split(".", 1)
    except ValueError:
        return None
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None
