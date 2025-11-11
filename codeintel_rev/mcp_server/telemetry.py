"""Telemetry helpers for MCP tools."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from codeintel_rev.app.middleware import get_capability_stamp, get_session_id
from codeintel_rev.observability.timeline import Timeline, current_or_new_timeline

__all__ = ["tool_operation_scope"]


@contextmanager
def tool_operation_scope(
    tool_name: str,
    **attrs: object,
) -> Iterator[Timeline]:
    """Emit start/end events for an MCP tool and yield the active timeline.

    Yields
    ------
    Timeline
        Active timeline bound to the current session or a new one when absent.
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
    with timeline.operation(f"mcp.tool.{tool_name}", **operation_attrs):
        yield timeline
