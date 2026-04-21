"""Page write toolset.

Off by default. Enables draft-and-publish flows:

    pages.create         Create a draft child under a parent page.
    pages.update         Update a page's fields; creates a new revision.
    pages.publish        Publish the latest revision.
    pages.unpublish      Unpublish a live page.
    pages.delete         Delete a page (requires ``ALLOW_DESTRUCTIVE``).
    pages.revert         Revert to a prior revision.

Every call respects Wagtail permissions and, for destructive ops, the
``LIMITS.ALLOW_DESTRUCTIVE`` gate in addition to the toolset flag.

StreamField writes go through the envelope + strict validator in
:mod:`wagtail_mcp_server.serializers.streamfield`. Unknown block types
or struct children raise before anything touches the database.

Landing in v0.2; v0.1 exports only the shell.
"""

from __future__ import annotations


class PageWriteToolset:
    """django-mcp-server toolset for page writes."""

    name = "pages_write"
    version = "0.1.0"
