# OpenTelemetry

`wagtail-mcp-server` emits a span for every tool call when an
OpenTelemetry SDK is configured in the host process. The library
**never configures the tracer provider or exporter itself** — the
host owns that.

```python
WAGTAIL_MCP_SERVER = {
    "AUDIT": {
        "ENABLED": True,
        "EMIT_OTEL": True,  # default in v0.5
    },
}
```

## What's emitted

Each tool call is wrapped in a span named:

```
wagtail_mcp_server.tool.<toolset>.<tool>
```

For example: `wagtail_mcp_server.tool.pages_query.pages.list`.

Span attributes:

| Attribute                      | Type   | Meaning                                  |
|--------------------------------|--------|------------------------------------------|
| `mcp.toolset`                  | string | Toolset slug (`pages_write`, etc).       |
| `mcp.tool`                     | string | Fully-qualified tool name.               |
| `mcp.user.id`                  | int    | Acting Django user id.                   |
| `mcp.user.username`            | string | Acting Django username.                  |
| `mcp.token.id`                 | int    | `UserMcpToken` id, if token-authed.      |
| `mcp.result.status`            | string | `ok` / `denied` / `error`.               |
| `mcp.result.summary`           | string | Same string written to the audit log.    |
| `mcp.latency_ms`               | int    | Includes permission checks.              |
| `enduser.id` (semconv)         | string | Same as `mcp.user.username`.             |

Errors raised from the tool body are recorded on the span with
`record_exception` and the span's status set to `ERROR`.

## When emission is a no-op

If no OTel SDK is configured in the host process, the library uses
the OTel API's *default* no-op tracer. Spans are created but
nothing is exported. Cost is a few microseconds per call and zero
network I/O. This is the case in any Django process where
`opentelemetry-sdk` isn't installed *or* hasn't been initialised.

The flip to `EMIT_OTEL=True` as the v0.5 default is safe precisely
because of this: a host that hasn't wired up an exporter doesn't
pay anything to have emission "on".

## Wiring it up in the host

Install the OTel extras:

```bash
pip install 'wagtail-mcp-server[otel]'
```

That pulls `opentelemetry-api`, `opentelemetry-sdk`, and the
HTTP-protobuf OTLP exporter.

Configure the SDK at process startup. For Django this typically
goes in `manage.py` or a small `wsgi.py` shim:

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

resource = Resource.create({
    "service.name": "wagtail-mcp",
    "service.version": "0.5.0",
    "deployment.environment": "prod",
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
```

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to your collector's URL:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otel-collector.example.com"
```

A locally-running OpenTelemetry Collector listening on the standard
`:4318/v1/traces` works without any further config.

## Disabling emission explicitly

```python
WAGTAIL_MCP_SERVER = {
    "AUDIT": {"EMIT_OTEL": False},
}
```

Useful if you want the audit row but not the span (for example, if
your span ingest is metered and you don't want MCP traffic to count
against it).

## Relationship to the audit log

OTel emission and the `ToolCall` audit row are independent. The audit
row is the durable, queryable record-of-truth; the OTel span is for
real-time observability and trace correlation.

If `AUDIT.ENABLED = False`, OTel emission is also off — there's no
useful "trace without record" mode.

## Gotchas

* The library uses *only* the OpenTelemetry API in its imports. The SDK is a host concern. This is what makes "emit by default" cheap.
* If you wrap the MCP HTTP view in your own middleware (e.g. for request-id propagation), make sure your tracer provider is initialised before the first request — otherwise the first call's span goes to a no-op tracer and you'll see a gap.
* Span names are stable across releases. Adding a new tool adds a new span name; renaming a tool would be a breaking change to the contract.
