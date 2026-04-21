"""Read-only page query toolset.

Implements in v0.1:

    pages.list           Paginated list of live pages, optionally filtered.
    pages.get            Full page payload with StreamField envelope.
    pages.tree           Ancestors + children of a given page.
    pages.search         Full-text search delegated to Wagtail search.
    pages.types          Names of registered ``Page`` subclasses.
    pages.types.schema   JSON schema for a specific page type.

All tools are side-effect free and safe to expose by default. Each tool
is scoped to pages the authenticated user has ``view_page`` on; Wagtail
permissions apply.

v0.1 scaffold: the implementation stubs live here so the class imports
cleanly. Real logic lands in the next task, hooked up through the
serializers module.
"""

from __future__ import annotations


class PageQueryToolset:
    """django-mcp-server toolset for read-only page access."""

    name = "pages_query"
    version = "0.1.0"

    # Tool handlers are registered via the django-mcp-server API; this
    # class will gain `@tool` decorators in the next task. Keeping the
    # shell here so the registry can import it without surprise.
