"""OpenTelemetry emission for wagtail-mcp-server.

On by default as of v0.5. No-op when the host process has not
configured an OpenTelemetry SDK, so the default is safe for every
install. Set ``WAGTAIL_MCP_SERVER["AUDIT"]["EMIT_OTEL"] = False`` to
suppress emission explicitly.

Design contract:
    - The host app owns the OTel SDK and the exporter. This module never
      calls ``set_tracer_provider`` and never spins up its own exporter.
    - When emission is on, every tool call emits a span named
      ``wagtail_mcp_server.tool.<toolset>.<tool>`` with attributes for
      user id, token label, input size, output size, and latency.
    - When emission is off, ``record_tool_call`` is a zero-cost no-op
      (no OTel import happens, no span object is allocated).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from .settings import get_config


def _emission_enabled() -> bool:
    return bool(get_config()["AUDIT"].get("EMIT_OTEL", False))


@contextmanager
def record_tool_call(toolset: str, tool: str, **attributes: Any):
    """Context manager that emits a span for a single tool call.

    No-op when OTel emission is disabled. The caller does not need to
    check the flag; calling this from within a tool handler is always safe.
    """
    if not _emission_enabled():
        yield None
        return

    # Import lazily so the OTel SDK is optional.
    try:
        from opentelemetry import trace  # noqa: PLC0415
    except ImportError:
        # OTel not installed; silently no-op. Operators asked for emission
        # but the extras group isn't installed; log once elsewhere if that
        # matters, but don't crash the tool call.
        yield None
        return

    tracer = trace.get_tracer("wagtail_mcp_server")
    span_name = f"wagtail_mcp_server.tool.{toolset}.{tool}"
    with tracer.start_as_current_span(span_name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise
