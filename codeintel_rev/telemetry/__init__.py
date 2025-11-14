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

__all__ = [
    "RunCheckpoint",
    "TimelineEvent",
    "attach_context_attrs",
    "checkpoint_event",
    "current_run_id",
    "current_session",
    "current_stage",
    "install_structured_logging",
    "request_tool_var",
    "run_id_var",
    "session_id_var",
    "set_request_stage",
    "telemetry_context",
    "trace_span",
    "trace_step",
]
