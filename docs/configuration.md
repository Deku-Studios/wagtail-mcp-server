# Configuration reference

All configuration lives under a single `WAGTAIL_MCP_SERVER` dict in your Django settings. Nothing leaks into the top-level settings namespace.

## Full shape

```python
WAGTAIL_MCP_SERVER = {
    "AUTH": {
        "BACKEND": "UserTokenAuth",   # or "BearerTokenAuth" (dev only)
        "ALLOW_IMPERSONATION": False,
    },
    "TOOLSETS": {
        "pages_query":       {"enabled": True},   # on by default (safe read)
        "seo_query":         {"enabled": True},   # on by default (safe read)
        "collections_query": {"enabled": True},   # on by default (safe read)
        "snippets_query":    {"enabled": True},   # on by default (safe read)
        "redirects": {                            # split-flag toolset
            "enabled_read":  True,                # read on by default
            "enabled_write": False,               # write off by default
        },
        "pages_write": {"enabled": False},  # off by default
        "workflow":    {"enabled": False},  # off by default
        "media":       {"enabled": False},  # off by default
        "seo_write":   {"enabled": False},  # off by default
    },
    "LIMITS": {
        "MAX_PAGE_SIZE": 50,
        "MAX_SEARCH_RESULTS": 100,
        "MAX_UPLOAD_MB": 25,
        "ALLOW_DESTRUCTIVE": False,
    },
    "RICHTEXT_FORMAT": "html",        # or "draftail"
    "WRITE_VALIDATION": "strict",     # or "permissive"
    "AUDIT": {
        "ENABLED": True,
        "RETENTION_DAYS": 90,
        "EMIT_OTEL": True,
    },
}
```

## Key reference

### `AUTH.BACKEND`

`UserTokenAuth` (default). Per-agent tokens bound to a single Django user. Recommended for production.

`BearerTokenAuth`. Single shared bearer token bound to a service user. Demoted to dev use. Reads `WAGTAIL_MCP_SERVER_DEV_TOKEN` and `WAGTAIL_MCP_SERVER_DEV_USER` from the environment.

### `AUTH.ALLOW_IMPERSONATION`

Default `False`. When `True`, a privileged agent token can include an `on_behalf_of` claim to run tool calls as another user. Leave off unless you have a concrete audited use case.

### `TOOLSETS.*.enabled`

Invariant: every write toolset is off by default. Flipping `pages_write` on does not turn on `workflow` or `media`. Each write toolset is an explicit opt-in.

A disabled toolset is **not imported** — config gating happens before `ToolsetMeta` ever runs, so disabled tools never appear on the MCP wire and never count against the host's import time.

### `TOOLSETS.redirects.enabled_read` / `enabled_write`

`redirects` is the only toolset in v0.5 that uses a split-flag config — its read side ships on by default, its write side ships off. Use the split-flag form for `redirects` only:

```python
"redirects": {"enabled_read": True, "enabled_write": False}
```

Other toolsets use the single `enabled` flag. The asymmetry exists because read-access to a redirect map is something an agent realistically needs at the audit-only tier, but write access is high-blast-radius (a wrong redirect can take a section of the site down).

### `LIMITS.MAX_PAGE_SIZE`

Default `50`. Maximum page size for any `.list` tool. Requests above the cap are clamped.

### `LIMITS.MAX_SEARCH_RESULTS`

Default `100`. Hard cap on search result count.

### `LIMITS.MAX_UPLOAD_MB`

Default `25`. Per-upload cap for `media.images.upload` and `media.documents.upload`. Uploads larger than this are rejected before touching disk.

### `LIMITS.ALLOW_DESTRUCTIVE`

Default `False`. Destructive operations (delete page, hard-delete image) require this flag **in addition to** the toolset flag and the user's Wagtail permission. Three gates, all required.

### `RICHTEXT_FORMAT`

`html` (default). RichText blocks serialize as HTML strings. Matches Wagtail's own API default and is what most LLM prompts expect.

`draftail`. Emit the Draftail JSON structure instead. Opt in when you need round-trip fidelity with Wagtail's in-admin editor.

### `WRITE_VALIDATION`

`strict` (default). Unknown top-level fields, unknown block types, and unknown struct child names on write all raise `StreamFieldValidationError` before the DB is touched. Errors carry a closed-vocabulary `code`, a `path` into the stream, and the expected-vs-got pair so the calling agent can self-correct.

`permissive`. Unknown fields and block types are silently dropped with a log warning. Use sparingly; strict is the supported mode.

### `AUDIT.ENABLED`

Default `True`. Every tool call is recorded to the `ToolCall` table.

### `AUDIT.RETENTION_DAYS`

Default `90`. As of v0.5, `python manage.py mcp_prune_audit` enforces the window against the `ToolCall` table. Schedule it via Celery beat, cron, or the host's equivalent. Flags: `--dry-run`, `--batch-size N`, `--older-than DAYS` (override the setting for a single run).

### `AUDIT.EMIT_OTEL`

Default `True` as of v0.5. When an OpenTelemetry SDK is configured in the host process, every tool call emits a span named `wagtail_mcp_server.tool.<toolset>.<tool>`. When no SDK is configured, emission is a silent no-op and costs nothing. The host app owns the tracer provider and exporter; this library never configures them. Set to `False` to suppress emission explicitly.
