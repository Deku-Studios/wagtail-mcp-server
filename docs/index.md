# wagtail-mcp-server

Expose a [Wagtail](https://wagtail.org/) CMS as a [Model Context
Protocol](https://modelcontextprotocol.io/) server so AI agents can read,
search, and (when you decide) modify your content with the same Django
permissions a human editor has.

`wagtail-mcp-server` is a BSD-3-licensed Django app. It plugs into an
existing Wagtail project as `INSTALLED_APPS += ["wagtail_mcp_server"]`,
or runs entirely on its own with the bundled `wagtail-mcp-serve`
console script.

## Why this exists

If you have a Wagtail site, agents are going to want to talk to it.
You can either:

1. Hand them an admin-token API and hope they never click delete, or
2. Give them a *narrow*, *audited*, *permission-aware* surface that
   speaks the same protocol Claude Desktop, Cursor, and the rest of
   the MCP ecosystem already understand.

This library is the second option. Reads are on by default; every
write toolset must be enabled explicitly; destructive operations
(unpublish, delete) need an additional flag *and* a Wagtail
permission. Every tool call is audited.

## Status

Released versions and what they shipped:

| Version | Headline |
|---------|----------|
| 0.1     | Scaffold, settings resolver, auth backends |
| 0.2     | First production toolsets, HTTP transport, CLI dispatcher |
| 0.3     | Workflow toolset, media toolset, SEO write toolset |
| 0.4     | Audit log + token introspection |
| 0.5     | Final-for-launch: collections, snippets, redirects, sitemap regen, media focal points, standalone `wagtail-mcp-serve` |

## Quick start

The fastest path to "an MCP endpoint I can point a client at" is the
standalone runtime — no Django project required:

```bash
pip install wagtail-mcp-server
wagtail-mcp-serve --stdio
# A first-boot bootstrap prints your superuser + token to stderr.
# Save the token; it is not shown again.
```

Then point Claude Desktop, Cursor, or any MCP-aware client at the
binary. See [Getting started](getting-started.md) for client config
snippets.

## Embedding in an existing Wagtail project

If you already run Wagtail, drop the app in:

```python
# settings.py
INSTALLED_APPS += ["wagtail_mcp_server"]

WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query":   {"enabled": True},
        # Writes opt-in only:
        # "pages_write": {"enabled": True},
    },
}
```

```python
# urls.py
urlpatterns += [path("mcp/", include("wagtail_mcp_server.urls"))]
```

Then mint a per-agent token:

```bash
python manage.py mcp_issue_token --user alice --label "Claude Desktop"
```

## What ships in the box

* **Eight toolsets** spanning pages, SEO, media, workflow, collections,
  snippets, and redirects. Each is gated by config and permissions.
* **Two transports** — HTTP (Streamable) for production, stdio for
  local desktop clients.
* **A pluggable auth model** — per-agent `UserMcpToken` (recommended)
  or a single shared bearer (dev only).
* **Audit log + retention** with optional OpenTelemetry export.
* **A standalone runtime** so people without a Wagtail project can
  still try the protocol with one command.

See [Configuration](configuration.md) for the full surface and
[Toolsets](toolsets/index.md) for the per-tool reference.
