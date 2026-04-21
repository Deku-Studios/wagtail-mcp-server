"""Read-only SEO toolset.

On by default (safe read):

    seo.get               SEO fields + computed metadata for a page.
    seo.sitemap           Current XML sitemap as a parsed list.
    seo.schema_org.get    Structured data (JSON-LD) for a page.

Lands in v0.2; v0.1 exports only the shell.
"""

from __future__ import annotations


class SEOQueryToolset:
    """django-mcp-server toolset for SEO reads."""

    name = "seo_query"
    version = "0.1.0"
