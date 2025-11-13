"""Typed event helpers shared across telemetry modules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "RunCheckpoint",
    "RunEventRecord",
    "TimelineEvent",
    "checkpoint_event",
    "coerce_event",
    "normalize_run_event",
]


@dataclass(slots=True, frozen=True)
class RunCheckpoint:
    """Structured checkpoint emitted after significant pipeline stages."""

    stage: str
    ok: bool
    reason: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_event_attrs(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary for downstream stores.

        Returns
        -------
        dict[str, Any]
            Attribute dictionary describing the checkpoint.
        """
        payload: dict[str, Any] = {"stage": self.stage, "ok": self.ok}
        if self.reason:
            payload["reason"] = self.reason
        payload.update(self.attrs)
        return payload


@dataclass(slots=True, frozen=True)
class TimelineEvent:
    """Normalized representation of a timeline entry."""

    session_id: str
    run_id: str
    ts: float
    type: str
    name: str
    status: str
    message: str | None
    attrs: dict[str, Any]


def checkpoint_event(
    stage: str, *, ok: bool, reason: str | None = None, **attrs: object
) -> RunCheckpoint:
    """Create a RunCheckpoint instance.

    This function constructs a RunCheckpoint event for tracking pipeline execution
    stages. Checkpoints record success/failure status, optional reason messages,
    and additional attributes for observability and debugging.

    Parameters
    ----------
    stage : str
        Stage identifier for the checkpoint (e.g., "index.build", "search.execute").
        Used to identify which pipeline stage the checkpoint represents.
    ok : bool
        Success status flag. True indicates the stage completed successfully,
        False indicates failure or error condition.
    reason : str | None, optional
        Optional reason message explaining the checkpoint status (default: None).
        Typically used to provide error messages or success summaries. Included
        in the checkpoint payload when provided.
    **attrs : object
        Additional keyword arguments to include as checkpoint attributes. All
        attributes are merged into the checkpoint's attrs dictionary for extended
        context and debugging information.

    Returns
    -------
    RunCheckpoint
        Structured checkpoint payload containing stage, ok status, reason, and
        attributes. The checkpoint is suitable for serialization and timeline
        recording.
    """
    return RunCheckpoint(stage=stage, ok=ok, reason=reason, attrs=dict(attrs))


def coerce_event(payload: Mapping[str, Any]) -> TimelineEvent:
    """Coerce a raw timeline payload into :class:`TimelineEvent`.

    This function converts a raw dictionary payload into a normalized TimelineEvent
    by extracting required fields (session_id, run_id, ts, type, name, status) and
    applying default values for missing fields. The function handles type coercion
    and ensures all fields are properly formatted.

    Parameters
    ----------
    payload : Mapping[str, Any]
        Raw timeline event payload dictionary. Expected keys include session_id,
        run_id, ts (timestamp), type, name, status, and optional attrs. Missing
        values are replaced with defaults (empty strings, 0.0 for timestamp, "ok"
        for status).

    Returns
    -------
    TimelineEvent
        Normalized timeline event with all required fields populated. The event
        is constructed from the payload with type coercion and default value
        handling for missing fields.
    """
    return TimelineEvent(
        session_id=str(payload.get("session_id", "")),
        run_id=str(payload.get("run_id", "")),
        ts=float(payload.get("ts", 0.0)),
        type=str(payload.get("type", "")),
        name=str(payload.get("name") or ""),
        status=str(payload.get("status") or "ok"),
        message=payload.get("message"),
        attrs=dict(payload.get("attrs") or {}),
    )


@dataclass(slots=True, frozen=True)
class RunEventRecord:
    """Structured representation of a run-level event."""

    ts: float
    session_id: str
    run_id: str
    component: str
    op: str
    status: str
    duration_ms: int | None = None
    input_size: int | None = None
    output_size: int | None = None
    batch_size: int | None = None
    resource_ids: tuple[str, ...] = ()
    trace_id: str | None = None
    span_id: str | None = None
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_context: dict[str, Any] = field(default_factory=dict)


def normalize_run_event(payload: Mapping[str, Any]) -> RunEventRecord:
    """Return a :class:`RunEventRecord` from ``payload`` with defaults applied.

    Parameters
    ----------
    payload : Mapping[str, Any]
        Raw event payload dictionary. Expected keys include ts, session_id, run_id,
        status, kind, detail, warnings, error_code, and error_context. Missing keys
        are filled with defaults.

    Returns
    -------
    RunEventRecord
        Normalized run event structure with defaults applied.
    """

    def _tuple(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Sequence):
            return tuple(str(item) for item in value)
        return ()

    error_ctx = payload.get("error_context")
    return RunEventRecord(
        ts=float(payload.get("ts", 0.0)),
        session_id=str(payload.get("session_id", "")),
        run_id=str(payload.get("run_id", "")),
        component=str(payload.get("component", "")),
        op=str(payload.get("op", "")),
        status=str(payload.get("status", "ok")),
        duration_ms=payload.get("duration_ms"),
        input_size=payload.get("input_size"),
        output_size=payload.get("output_size"),
        batch_size=payload.get("batch_size"),
        resource_ids=_tuple(payload.get("resource_ids", ())),
        trace_id=_maybe_str(payload.get("trace_id")),
        span_id=_maybe_str(payload.get("span_id")),
        warnings=_tuple(payload.get("warnings", ())),
        error_code=_maybe_str(payload.get("error_code")),
        error_context=dict(error_ctx or {}),
    )


def _maybe_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
