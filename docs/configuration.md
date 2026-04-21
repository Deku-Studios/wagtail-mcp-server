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
        "pages_query": {"enabled": True},   # on by default (safe read)
        "seo_query":   {"enabled": True},   # on by default (safe read)
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
        "EMIT_OTEL": False,
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

Default `90`. Pruning is out of scope for v0.1; intend to run a Celery beat task or a management command on this schedule.

### `AUDIT.EMIT_OTEL`

Default `False`. When `True` and the optional `otel` extras group is installed, every tool call emits a span named `wagtail_mcp_server.tool.<toolset>.<tool>`. The host app owns the tracer provider and exporter; this library never configures them.
