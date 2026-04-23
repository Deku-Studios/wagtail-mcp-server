# Auditing

Every tool call is recorded to a `ToolCall` row when
`AUDIT.ENABLED` is `True` (the default). The audit log is the
primary forensic artefact for "what did this agent do, and was it
allowed to?"

## What gets recorded

For every invocation:

| Field             | Type        | Notes                                       |
|-------------------|-------------|---------------------------------------------|
| `id`              | BigAutoField | Stable across the lifetime of the row.     |
| `created_at`      | datetime    | Indexed.                                    |
| `user`            | FK          | The Django user the token resolved to.      |
| `token`           | FK          | The `UserMcpToken` row that authenticated. Nullable for backend / system calls. |
| `toolset`         | str         | E.g. `pages_query`.                         |
| `tool`            | str         | E.g. `pages.update`.                        |
| `arguments_json`  | JSON        | The arguments the agent supplied.           |
| `result_status`   | str         | `ok`, `denied`, `error`.                    |
| `result_summary`  | str         | Short string for grep-ability.              |
| `latency_ms`      | int         | End-to-end including permission checks.     |
| `client_ip`       | str         | From the request, when available.           |

`arguments_json` is stored verbatim — including any redacted
chooser refs and StreamField bodies. For a multi-tenant deployment
this is sensitive; see [Retention](#retention) below.

## Reading the log

It's a Django model, so use whatever you'd reach for normally:

```python
from wagtail_mcp_server.models import ToolCall

ToolCall.objects.filter(
    toolset="pages_write",
    result_status="denied",
    created_at__gte=last_week,
).order_by("-created_at")[:50]
```

For ad-hoc operator inspection there's a small management command:

```bash
python manage.py mcp_audit_tail --user alice --toolset pages_write --limit 50
```

It accepts `--user`, `--toolset`, `--tool`, `--status`, `--since`,
and `--limit` and prints a tab-separated tail. Useful for
post-incident review when the Django admin is too slow.

## Retention

```python
WAGTAIL_MCP_SERVER = {
    "AUDIT": {
        "ENABLED": True,
        "RETENTION_DAYS": 90,  # default
    },
}
```

Setting `RETENTION_DAYS` doesn't itself delete anything. Pruning is
explicit, so you can wire it into whatever scheduler your project
uses:

```bash
python manage.py mcp_prune_audit
```

Flags:

* `--dry-run` — count what would be deleted, don't delete.
* `--batch-size N` — chunk DELETEs to keep transactions small. Default 1000.
* `--older-than DAYS` — override `RETENTION_DAYS` for a single run.

A typical prod schedule is a daily cron at off-peak:

```bash
0 4 * * * cd /srv/app && python manage.py mcp_prune_audit
```

If you also use Celery beat:

```python
CELERY_BEAT_SCHEDULE = {
    "wagtail-mcp-server.prune-audit": {
        "task": "django.core.management.call_command",
        "args": ("mcp_prune_audit",),
        "schedule": crontab(hour=4, minute=0),
    },
}
```

## Disabling

```python
WAGTAIL_MCP_SERVER = {
    "AUDIT": {"ENABLED": False},
}
```

Disables audit row creation entirely. The `ToolCall` table will
still exist (it's part of the schema), it just won't accumulate
rows. Useful for ephemeral test environments.

Disabling audit also disables OTel emission; see
[OpenTelemetry](otel.md) for more on the relationship between the two.

## Gotchas

* `arguments_json` is **not** scrubbed of PII by the library. If your tools accept email addresses, names, or other regulated data and you need to redact them in the audit trail, hook into the pre-save signal on `ToolCall` and rewrite the field there.
* Pruning runs in chunks but is still I/O. On a large table the first run after enabling retention can take a while; use `--dry-run` first to size it.
* Pruning never deletes a `ToolCall` whose `created_at` is `NULL` (defensive — this should never happen, but the guard is there in case data was loaded out-of-band).
