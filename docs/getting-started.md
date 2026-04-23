# Getting started

Two paths, depending on whether you already have a Wagtail project.

## Path A: standalone runtime (no project)

```bash
pip install wagtail-mcp-server
wagtail-mcp-serve --stdio
```

That's it. The first run:

1. Lays down a SQLite database under
   `~/.local/share/wagtail-mcp-server/db.sqlite3` (or the platform
   equivalent — see [Standalone runtime](standalone.md)).
2. Generates and persists a `SECRET_KEY` so subsequent boots don't
   invalidate sessions.
3. Creates a superuser named `admin` (random password) and mints
   one MCP token. **Both are printed to stderr exactly once.** Save
   the token.

Subsequent boots reuse the same data dir and skip the bootstrap.

## Path B: existing Wagtail project

### 1. Install

```bash
pip install wagtail-mcp-server
```

### 2. Add to `INSTALLED_APPS`

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "wagtail_mcp_server",
]

WAGTAIL_MCP_SERVER = {
    "AUTH": {"BACKEND": "UserTokenAuth"},
    "TOOLSETS": {
        "pages_query": {"enabled": True},
        "seo_query":   {"enabled": True},
        "collections_query": {"enabled": True},
        "snippets_query": {"enabled": True},
        # Read of redirects on, write off (the v0.5 split-flag default):
        "redirects": {"enabled_read": True, "enabled_write": False},
        # Opt-in only:
        # "pages_write": {"enabled": True},
        # "media":       {"enabled": True},
        # "seo_write":   {"enabled": True},
        # "workflow":    {"enabled": True},
    },
    "AUDIT": {"ENABLED": True, "RETENTION_DAYS": 90},
}
```

### 3. Mount the URL

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    # ... your existing routes ...
    path("mcp/", include("wagtail_mcp_server.urls")),
]
```

### 4. Migrate

```bash
python manage.py migrate
```

This creates the `UserMcpToken` and `ToolCall` tables.

### 5. Mint a token per agent

```bash
python manage.py mcp_issue_token --user alice --label "Claude Desktop"
```

The plaintext token is printed once to stdout. Hand it to the agent
that will use it; you cannot retrieve it again.

## Connecting an MCP client

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the Windows / Linux equivalent:

=== "Standalone runtime"

    ```json
    {
      "mcpServers": {
        "wagtail": {
          "command": "wagtail-mcp-serve",
          "args": ["--stdio"]
        }
      }
    }
    ```

=== "Existing Django project"

    ```json
    {
      "mcpServers": {
        "wagtail": {
          "command": "python",
          "args": ["manage.py", "mcp_serve", "--stdio"],
          "cwd": "/path/to/your/django/project",
          "env": {
            "WAGTAIL_MCP_SERVER_TOKEN": "your-token-from-mcp_issue_token"
          }
        }
      }
    }
    ```

### Cursor

Cursor's MCP config lives at `~/.cursor/mcp.json` and uses the same
schema as Claude Desktop. Reuse one of the snippets above.

### HTTP clients (Inspector, custom agents)

```bash
# Hit the MCP endpoint with a Bearer token:
curl -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

## Verifying the surface

```bash
python manage.py mcp_introspect
```

Lists every enabled toolset, the tools it exposes, and their JSON
schemas. Use this to confirm the agent will see what you expect
before pointing it at production.

## Next steps

* [Configuration](configuration.md) — full reference for the
  `WAGTAIL_MCP_SERVER` settings dict.
* [Toolsets](toolsets/index.md) — what each toolset does and what
  permissions it needs.
* [Operations](operations/audit.md) — auditing, OpenTelemetry, and
  token rotation.
