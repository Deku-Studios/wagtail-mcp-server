# wagtail-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a [Wagtail](https://wagtail.org/) CMS to AI agents. Built on top of [django-mcp-server](https://github.com/gts360/django-mcp-server).

**Status:** Alpha, pre-1.0. API and config shape may change.
**License:** BSD-3-Clause.
**Minimum versions:** Wagtail 7.3.1, Django 5.0, Python 3.11.

## What it is

A reusable Django app you can drop into any Wagtail project to give an AI agent (Claude, Lex, Cursor, any MCP client) safe, scoped tools for:

- Reading pages, images, documents, and the page tree.
- Drafting, updating, and previewing pages without publishing.
- Moving pages through a Wagtail workflow (submit for moderation, approve, reject).
- Uploading media and managing metadata.
- Reading and updating SEO fields and sitemaps.

Writes are off by default. Read tools (`pages_query`, `seo_query`) are on by default and safe. Every write toolset (`pages_write`, `workflow`, `media`, `seo_write`) is an opt-in that also respects the logged-in user's Wagtail permissions.

## What it is not

Not a replacement for Wagtail's admin UI. Not a way to bypass Wagtail permissions, workflow, or revisions. Not a pass-through for arbitrary Django ORM access.

## Install

```bash
pip install wagtail-mcp-server
```

Add to `INSTALLED_APPS` after `wagtail.core` (or `wagtail` in 7.x):

```python
INSTALLED_APPS = [
    # ... your apps ...
    "wagtail_mcp_server",
]
```

Mount the ASGI route (in your project `urls.py`):

```python
from django.urls import include, path

urlpatterns = [
    # ... your patterns ...
    path("mcp/", include("wagtail_mcp_server.urls")),
]
```

Run migrations:

```bash
python manage.py migrate wagtail_mcp_server
```

Issue a per-agent token:

```bash
python manage.py mcp_issue_token --user lex-agent --label "Lex Nanobot"
```

## Configure

All settings live under a single `WAGTAIL_MCP_SERVER` dict so nothing leaks into your project namespace. Defaults are shown; override only what you need.

```python
WAGTAIL_MCP_SERVER = {
    "AUTH": {
        "BACKEND": "UserTokenAuth",
        "ALLOW_IMPERSONATION": False,
    },
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query": {"enabled": True},
        "pages_write": {"enabled": False},
        "workflow": {"enabled": False},
        "media": {"enabled": False},
        "seo_write": {"enabled": False},
    },
    "LIMITS": {
        "MAX_PAGE_SIZE": 50,
        "MAX_SEARCH_RESULTS": 100,
        "MAX_UPLOAD_MB": 25,
        "ALLOW_DESTRUCTIVE": False,
    },
    "RICHTEXT_FORMAT": "html",   # or "draftail"
    "WRITE_VALIDATION": "strict", # or "permissive"
    "AUDIT": {
        "ENABLED": True,
        "RETENTION_DAYS": 90,
        "EMIT_OTEL": False,
    },
}
```

See [docs/configuration.md](docs/configuration.md) for the full reference.

## Client configs

### Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wagtail": {
      "command": "wagtail-mcp-server",
      "args": ["serve", "--stdio"],
      "env": {
        "DJANGO_SETTINGS_MODULE": "yourproject.settings",
        "WAGTAIL_MCP_SERVER_TOKEN": "<token from mcp_issue_token>"
      }
    }
  }
}
```

### Cursor

In `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "wagtail": {
      "command": "wagtail-mcp-server",
      "args": ["serve", "--stdio"],
      "env": {
        "DJANGO_SETTINGS_MODULE": "yourproject.settings",
        "WAGTAIL_MCP_SERVER_TOKEN": "<token>"
      }
    }
  }
}
```

### HTTP / SSE (for hosted agents)

Any MCP client that speaks HTTP+SSE can hit the mounted route directly with `Authorization: Bearer <token>`.

## CLI

```bash
wagtail-mcp-server serve --stdio         # run over stdio (Claude Desktop, Cursor)
wagtail-mcp-server serve --http --port 8765   # run over HTTP+SSE
wagtail-mcp-server introspect             # list enabled toolsets + tools + JSON schemas
wagtail-mcp-server issue-token --user lex --label "Lex Nanobot"
wagtail-mcp-server revoke-token <token-id-or-prefix>
```

The CLI is a thin wrapper over the equivalent `manage.py` commands. Both work.

## Security model

- Tokens are scoped to a single Django user. The tool call runs as that user; Wagtail permissions apply.
- Impersonation is off by default. Turn it on only for trusted operators.
- Write toolsets are individually opt-in. Enabling `pages_write` does not enable `workflow` or `media`.
- Destructive operations (delete page, hard-delete image) require `LIMITS.ALLOW_DESTRUCTIVE = True` in addition to the toolset flag and the user's Wagtail permission. Three gates.
- Every tool call is logged to the `ToolCall` audit table with inputs, outputs, latency, and user. Retention is configurable.

## Observability

OpenTelemetry emission is built in and gated behind `AUDIT.EMIT_OTEL`. When enabled, every tool call emits a span named `wagtail_mcp_server.tool.<toolset>.<tool>`. The host app owns the exporter; the server attaches to whatever OTel SDK is configured in the Django process.

## Development

```bash
git clone https://github.com/Deku-Studios/wagtail-mcp-server
cd wagtail-mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

CI runs on Python 3.11 / 3.12 against Wagtail 7.3.1 and Wagtail main.

## Roadmap

- v0.1: PageQueryToolset, SEOQueryToolset, ToolCall audit, UserTokenAuth.
- v0.2: PageWriteToolset, WorkflowToolset, MediaToolset, SEOWriteToolset, StreamField envelope, CLI, OTel emission.
- v0.3: Collections and search integration, sitemap write, Wagtail 7.4 LTS floor, plugin hooks.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Discussions happen in [GitHub Discussions](https://github.com/Deku-Studios/wagtail-mcp-server/discussions). Bugs and feature requests go to [Issues](https://github.com/Deku-Studios/wagtail-mcp-server/issues).

## Related

- [Wagtail](https://wagtail.org/) — the CMS this wraps.
- [django-mcp-server](https://github.com/gts360/django-mcp-server) — the MCP transport we build on.
- [Model Context Protocol](https://modelcontextprotocol.io) — the open protocol for LLM tool use.
