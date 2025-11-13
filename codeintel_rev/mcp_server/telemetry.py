"""Telemetry helpers for MCP tools."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from codeintel_rev.app.middleware import get_capability_stamp, get_session_id
from codeintel_rev.observability.otel import as_span, record_span_event
from codeintel_rev.observability.timeline import Timeline, current_or_new_timeline
from codeintel_rev.telemetry.context import telemetry_context
from codeintel_rev.telemetry.prom import observe_request_latency
from codeintel_rev.telemetry.reporter import finalize_run, start_run

__all__ = ["tool_operation_scope"]


@contextmanager
def tool_operation_scope(
    tool_name: str,
    **attrs: object,
) -> Iterator[Timeline]:
    """Emit start/end events for an MCP tool and yield the active timeline.

    Extended Summary
    ----------------
    This context manager emits timeline events for MCP tool operations, providing
    observability into tool execution. It yields the active timeline (from context
    or newly created) and emits start/end events with optional attributes. Used
    throughout MCP tool handlers to track operation timing and context.

    Parameters
    ----------
    tool_name : str
        Name of the MCP tool being executed (e.g., "search.semantic", "symbols.search").
        Used in timeline event names and telemetry.
    **attrs : object
        Optional keyword arguments to include in timeline events as attributes.
        Common attributes include query_chars, limit, path, line, character, etc.

    Yields
    ------
    Timeline
        Active timeline bound to the current session or a new one when absent.
        The timeline is used to emit operation events and track execution context.

    Notes
    -----
    This context manager integrates with the timeline system to provide structured
    logging and observability. Events are emitted at context entry and exit with
    duration tracking. Time complexity: O(1) for context setup and event emission.

    Raises
    ------
    BaseException
        Any exception raised within the context is caught, recorded on the span
        with error status, and re-raised using Python's bare ``raise`` statement.
        The context manager ensures proper span cleanup and error attribution even
        when exceptions occur. Exceptions propagate to the caller after error recording.
        Note: Exceptions are re-raised (not directly raised), preserving the original
        exception traceback and propagating through this context manager.
    """
    try:
        session_id = get_session_id()
    except RuntimeError:
        session_id = None
    capability_stamp = get_capability_stamp()
    operation_attrs = dict(attrs)
    if session_id is not None:
        operation_attrs.setdefault("session_id", session_id)
    if capability_stamp is not None:
        operation_attrs.setdefault("capability_stamp", capability_stamp)
    timeline = current_or_new_timeline(session_id=session_id)
    start_run(
        timeline.session_id,
        timeline.run_id,
        tool_name=tool_name,
        capability_stamp=capability_stamp,
    )
    span_attrs = {
        "tool": tool_name,
        "session_id": timeline.session_id,
        "run_id": timeline.run_id,
    }
    with telemetry_context(
        session_id=timeline.session_id,
        run_id=timeline.run_id,
        capability_stamp=capability_stamp,
        tool_name=tool_name,
    ):
        timing_start = time.perf_counter()
        with as_span(f"mcp.tool.{tool_name}", **span_attrs):
            try:
                with timeline.operation(f"mcp.tool.{tool_name}", **operation_attrs):
                    yield timeline
            except BaseException as exc:
                record_span_event(
                    "mcp.tool.error",
                    tool=tool_name,
                    error=str(exc),
                )
                finalize_run(
                    timeline.session_id,
                    timeline.run_id,
                    status="error",
                    stop_reason=f"{type(exc).__name__}: {exc}",
                    finished_at=time.time(),
                )
                observe_request_latency(tool_name, time.perf_counter() - timing_start, "error")
                raise
            else:
                duration = time.perf_counter() - timing_start
                record_span_event(
                    "mcp.tool.complete",
                    tool=tool_name,
                    duration_ms=int(duration * 1000),
                )
                finalize_run(
                    timeline.session_id,
                    timeline.run_id,
                    status="complete",
                    finished_at=time.time(),
                )
                observe_request_latency(tool_name, duration, "complete")
