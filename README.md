# wagtail-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a [Wagtail](https://wagtail.org/) CMS to AI agents. Built on top of [django-mcp-server](https://github.com/gts360/django-mcp-server).

**Status:** Alpha, pre-1.0. Current tag: **v0.4.0**. API and config shape may change.
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

## Setup

There are four settings changes and one URL mount. All five are required.

### 1. Install

PyPI release is not yet published. Install from a git tag:

```bash
pip install "git+https://github.com/Deku-Studios/wagtail-mcp-server@v0.4.0"
```

`django-mcp-server` is a transitive dependency; pip resolves it automatically.

### 2. `INSTALLED_APPS` — add two apps

You need **both** `mcp_server` (the transport library) and `wagtail_mcp_server` (this package). Without `mcp_server`, the upstream `AppConfig.ready()` hook that fires `autodiscover_modules("mcp")` never runs, so no toolsets register and `tools/list` returns only the built-in `get_server_instructions`.

```python
INSTALLED_APPS = [
    # ... your apps ...
    "mcp_server",            # django-mcp-server transport
    "wagtail_mcp_server",    # this package
]
```

### 3. URL mount

In your project `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    # ... your patterns ...
    path("mcp/", include("wagtail_mcp_server.urls")),
]
```

`wagtail_mcp_server.urls` publishes `MCPServerStreamableHttpView` at the empty path, so the effective endpoint is `/mcp/`. Do **not** `include("mcp_server.urls")` — that would double-prefix to `/mcp/mcp/`.

### 4. Server name (optional but recommended)

Upstream django-mcp-server uses this dict to name the server in the MCP handshake. Setting it explicitly keeps Cursor / Claude Desktop connection panes legible:

```python
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    "name": "wagtail-mcp-server",
}
```

### 5. `WAGTAIL_MCP_SERVER` config

All server config lives under one dict so nothing leaks into your project namespace. Defaults are shown; override only what you need.

```python
WAGTAIL_MCP_SERVER = {
    "AUTH": {
        "BACKEND": "UserTokenAuth",
        "ALLOW_IMPERSONATION": False,
    },
    "TOOLSETS": {
        # Read-only, on by default.
        "pages_query": {"enabled": True},   # pages.list/get/tree/search/types/types.schema
        "seo_query":   {"enabled": True},   # seo.get / seo.audit / seo.sitemap

        # Write toolsets. Off by default. Flip individually; enabling one
        # never enables another. All writes still respect Wagtail's per-object
        # permissions on the authenticating user.
        "pages_write": {"enabled": False},  # pages.create/update/publish/unpublish/delete/move
        "workflow":    {"enabled": False},  # workflow.submit/approve/reject/cancel/state
        "media":       {"enabled": False},  # media.images.* and media.documents.*
        "seo_write":   {"enabled": False},  # seo.update
    },
    "LIMITS": {
        "MAX_PAGE_SIZE": 50,
        "MAX_SEARCH_RESULTS": 100,
        "MAX_UPLOAD_MB": 25,
        # Third gate for delete ops. Even when pages_write is on and the
        # user has Wagtail delete perms, `pages.delete` requires this flag.
        "ALLOW_DESTRUCTIVE": False,
    },
    # "html" serves richtext as HTML strings (best for agents). Flip to
    # "draftail" for JSON round-trip fidelity with Wagtail's admin editor.
    "RICHTEXT_FORMAT": "html",
    # "strict" rejects unknown block types + unknown struct children on
    # write before hitting the DB. Errors carry closed-vocab `code` +
    # `path` so the agent can self-correct. "permissive" tolerates unknowns.
    "WRITE_VALIDATION": "strict",
    "AUDIT": {
        "ENABLED": True,
        "RETENTION_DAYS": 90,
        # When True, every tool call emits a span named
        # `wagtail_mcp_server.tool.<toolset>.<tool>` via the host process's
        # OpenTelemetry SDK.
        "EMIT_OTEL": False,
    },
}
```

### 6. Migrate

```bash
python manage.py migrate wagtail_mcp_server
```

Creates `UserMcpToken`, `ToolCall`, `AgentScratchpad`. Token issuance is blocked until this runs.

### 7. Issue a token

Each agent gets its own token, scoped to one Django user. The plaintext is shown once — store it in the client config immediately.

```bash
python manage.py mcp_issue_token --user lex-agent --label "Lex Nanobot"
```

Revoke later with either the primary-key integer or the 8-char prefix shown at mint time:

```bash
python manage.py mcp_revoke_token 42
# or
python manage.py mcp_revoke_token a1b2c3d4
```

See [docs/configuration.md](docs/configuration.md) for the full settings reference.

## Connect an MCP client

The endpoint is streamable HTTP at `/mcp/`. Auth is `Authorization: Bearer <token>`. The server runs in stateful mode, so clients must complete the `initialize` handshake before calling tools; every MCP-compliant client handles that automatically.

### Claude Desktop

Claude Desktop ships with stdio transport only, so you proxy the remote HTTP endpoint through [`mcp-remote`](https://github.com/geelen/mcp-remote). In `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "wagtail": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://your-site.example.com/mcp/",
        "--header",
        "Authorization:Bearer ${WAGTAIL_MCP_TOKEN}"
      ],
      "env": {
        "WAGTAIL_MCP_TOKEN": "<paste token from mcp_issue_token>"
      }
    }
  }
}
```

Restart Claude Desktop. The hammer icon in the compose box should show `wagtail` with the enabled tools.

### Cursor

Cursor speaks streamable HTTP natively. In `.cursor/mcp.json` (project-local) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "wagtail": {
      "url": "https://your-site.example.com/mcp/",
      "headers": {
        "Authorization": "Bearer <paste token from mcp_issue_token>"
      }
    }
  }
}
```

Restart Cursor. The server appears under Settings → MCP with a green status dot when the handshake succeeds.

### Any MCP client

Any client that speaks MCP streamable HTTP can connect directly. POST to `/mcp/` with `Authorization: Bearer <token>`; the server responds with `Mcp-Session-Id` on the `initialize` call, which the client must echo on every subsequent request.

## Security model

- Tokens are scoped to a single Django user. Every tool call runs as that user; Wagtail permissions apply.
- Impersonation is off by default. Turn it on only for trusted operators.
- Write toolsets are individually opt-in. Enabling `pages_write` does not enable `workflow` or `media`.
- Destructive operations (delete page, hard-delete image) require `LIMITS.ALLOW_DESTRUCTIVE = True` in addition to the toolset flag and the user's Wagtail permission. Three gates.
- `media` refuses to mint presigned upload URLs unless Django's `default_storage` is `django-storages`' `S3Storage` (or a compatible backend). `FileSystemStorage` raises loudly — loud failure beats silent misconfiguration in local dev.
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

- **v0.1** (shipped): `PageQueryToolset`, read-path serializers, JSON Schema generator.
- **v0.2** (shipped): `PageWriteToolset`, `SEOQueryToolset`, StreamField write-path validator, audit migrations.
- **v0.3** (shipped): `WorkflowToolset`, `MediaToolset` (presign + finalize flow), `SEOWriteToolset`.
- **v0.4** (current): HTTP transport wired, `UserTokenDRFAuth` adapter, direct `MCPToolset` inheritance, config-gated autodiscover.
- **v0.5** (planned): CLI entrypoint for stdio transport, OTel emission on by default, Collections + search integration, sitemap write, Wagtail 7.4 LTS floor.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Discussions happen in [GitHub Discussions](https://github.com/Deku-Studios/wagtail-mcp-server/discussions). Bugs and feature requests go to [Issues](https://github.com/Deku-Studios/wagtail-mcp-server/issues).

## Related

- [Wagtail](https://wagtail.org/) — the CMS this wraps.
- [django-mcp-server](https://github.com/gts360/django-mcp-server) — the MCP transport we build on.
- [Model Context Protocol](https://modelcontextprotocol.io) — the open protocol for LLM tool use.
