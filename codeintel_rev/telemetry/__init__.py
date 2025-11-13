"""Phase-0 telemetry helpers (tracing, metrics, logging, run reports)."""

from __future__ import annotations

from codeintel_rev.telemetry.context import (
    attach_context_attrs,
    current_run_id,
    current_session,
    current_stage,
    request_tool_var,
    run_id_var,
    session_id_var,
    set_request_stage,
    telemetry_context,
)
from codeintel_rev.telemetry.decorators import trace_span, trace_step
from codeintel_rev.telemetry.events import RunCheckpoint, TimelineEvent, checkpoint_event
from codeintel_rev.telemetry.logging import install_structured_logging
from codeintel_rev.telemetry.otel import install_otel
from codeintel_rev.telemetry.prom import (
    MetricsConfig,
    build_metrics_router,
    observe_request_latency,
)

__all__ = [
    "MetricsConfig",
    "RunCheckpoint",
    "TimelineEvent",
    "attach_context_attrs",
    "build_metrics_router",
    "checkpoint_event",
    "current_run_id",
    "current_session",
    "current_stage",
    "install_otel",
    "install_structured_logging",
    "observe_request_latency",
    "request_tool_var",
    "run_id_var",
    "session_id_var",
    "set_request_stage",
    "telemetry_context",
    "trace_span",
    "trace_step",
]
