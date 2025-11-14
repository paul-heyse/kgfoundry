"""Telemetry helpers for MCP tools."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from codeintel_rev.app.middleware import get_capability_stamp, get_session_id
from codeintel_rev.observability.ledger import RunLedger, dated_run_dir
from codeintel_rev.observability.otel import record_span_event
from codeintel_rev.observability.reporting import render_run_report
from codeintel_rev.observability.runtime_observer import bind_run_ledger, current_run_ledger
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.observability.timeline import Timeline, current_or_new_timeline
from codeintel_rev.telemetry.context import telemetry_context
from codeintel_rev.telemetry.decorators import span_context
from codeintel_rev.telemetry.prom import observe_request_latency
from codeintel_rev.telemetry.reporter import finalize_run, start_run
from kgfoundry_common.logging import get_logger

__all__ = ["tool_operation_scope"]
LOGGER = get_logger(__name__)


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
    operation_attrs: dict[str, object] = dict(attrs)
    if session_id is not None:
        operation_attrs.setdefault("session_id", session_id)
    if capability_stamp is not None:
        operation_attrs.setdefault("capability_stamp", capability_stamp)
    timeline = current_or_new_timeline(session_id=session_id)
    operation_attrs.setdefault("run_id", timeline.run_id)
    start_run(
        timeline.session_id,
        timeline.run_id,
        tool_name=tool_name,
        capability_stamp=capability_stamp,
    )
    operation_name = f"mcp.tool:{tool_name}"
    ledger = current_run_ledger()
    ledger_owner = False
    if ledger is None:
        try:
            ledger_dir = dated_run_dir(None)
            ledger = RunLedger.open(ledger_dir, run_id=timeline.run_id, session_id=session_id)
            ledger_owner = True
        except (OSError, RuntimeError, ValueError):  # pragma: no cover - defensive
            ledger = None

    with telemetry_context(
        session_id=timeline.session_id,
        run_id=timeline.run_id,
        capability_stamp=capability_stamp,
        tool_name=tool_name,
    ):
        timing_start = time.perf_counter()
        otel_attrs: dict[str, object] = {
            Attrs.MCP_TOOL: tool_name,
            Attrs.MCP_SESSION_ID: timeline.session_id or "",
            Attrs.MCP_RUN_ID: timeline.run_id,
        }
        for key, value in attrs.items():
            otel_attrs.setdefault(key, value)
        with (
            bind_run_ledger(ledger),
            span_context(
                f"mcp.tool:{tool_name}",
                kind="server",
                attrs=otel_attrs,
            ),
        ):
            try:
                with timeline.operation(operation_name, **operation_attrs):
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
                _maybe_render_report(timeline)
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
                _maybe_render_report(timeline)
                observe_request_latency(tool_name, duration, "complete")
    if ledger_owner and ledger is not None:
        ledger.close()


def _maybe_render_report(timeline: Timeline) -> None:
    if not timeline.sampled:
        return
    try:
        render_run_report(timeline)
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - best-effort reporting
        LOGGER.debug("Failed to render run report", exc_info=exc)
