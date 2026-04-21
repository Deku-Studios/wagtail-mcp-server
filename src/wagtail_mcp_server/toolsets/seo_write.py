"""SEO write toolset.

Off by default. Updates SEO fields and (later) the sitemap config:

    seo.update            Update title, description, slug, canonical, OG fields.

Lands in v0.2.
"""

from __future__ import annotations


class SEOWriteToolset:
    """django-mcp-server toolset for SEO writes."""

    name = "seo_write"
    version = "0.1.0"
