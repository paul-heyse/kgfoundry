"""In-memory run report builder fed by timeline events."""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.telemetry.context import (
    attach_context_attrs,
    current_run_id,
    current_session,
)
from codeintel_rev.telemetry.events import RunCheckpoint, TimelineEvent, checkpoint_event, coerce_event

__all__ = [
    "RunReport",
    "RunReportStore",
    "RUN_REPORT_STORE",
    "build_report",
    "emit_checkpoint",
    "record_timeline_payload",
    "start_run",
    "finalize_run",
]


def _env_retention() -> int:
    raw = os.getenv("RUN_REPORT_RETENTION", "100").strip()
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(10, min(5000, value))


@dataclass(slots=True)
class RunRecord:
    """Mutable storage for a sampled run."""

    session_id: str
    run_id: str
    tool_name: str | None = None
    capability_stamp: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    status: str = "running"
    stop_reason: str | None = None
    operation_name: str | None = None
    events: list[TimelineEvent] = field(default_factory=list)
    checkpoints: list[RunCheckpoint] = field(default_factory=list)

    def clone(self) -> "RunRecord":
        """Return a shallow copy suitable for read-only processing."""

        return RunRecord(
            session_id=self.session_id,
            run_id=self.run_id,
            tool_name=self.tool_name,
            capability_stamp=self.capability_stamp,
            started_at=self.started_at,
            finished_at=self.finished_at,
            status=self.status,
            stop_reason=self.stop_reason,
            operation_name=self.operation_name,
            events=list(self.events),
            checkpoints=list(self.checkpoints),
        )


@dataclass(slots=True)
class RunReport:
    """Structured run summary consumable by humans and automation."""

    session_id: str
    run_id: str
    status: str
    stop_reason: str | None
    started_at: float | None
    finished_at: float | None
    operations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    checkpoints: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    summary: dict[str, Any]
    capabilities: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "operations": self.operations,
            "steps": self.steps,
            "decisions": self.decisions,
            "warnings": self.warnings,
            "errors": self.errors,
            "checkpoints": self.checkpoints,
            "timeline": self.timeline,
            "summary": self.summary,
            "capabilities": self.capabilities,
        }


class RunReportStore:
    """Thread-safe circular buffer of run data."""

    def __init__(self, retention: int) -> None:
        self._retention = retention
        self._records: dict[tuple[str, str], RunRecord] = {}
        self._order: deque[tuple[str, str]] = deque()
        self._lock = threading.Lock()

    def _ensure_record(self, session_id: str, run_id: str) -> RunRecord:
        key = (session_id, run_id)
        record = self._records.get(key)
        if record is None:
            record = RunRecord(session_id=session_id, run_id=run_id)
            self._records[key] = record
            self._order.append(key)
            self._trim_locked()
        return record

    def _trim_locked(self) -> None:
        while len(self._order) > self._retention:
            victim = self._order.popleft()
            self._records.pop(victim, None)

    def start_run(
        self,
        session_id: str,
        run_id: str,
        *,
        tool_name: str | None,
        capability_stamp: str | None,
        started_at: float | None = None,
    ) -> None:
        with self._lock:
            record = self._ensure_record(session_id, run_id)
            record.tool_name = tool_name
            record.capability_stamp = capability_stamp
            record.started_at = record.started_at or started_at

    def record_event(self, event: TimelineEvent) -> None:
        if not event.session_id or not event.run_id:
            return
        with self._lock:
            record = self._ensure_record(event.session_id, event.run_id)
            record.events.append(event)
            if event.type == "operation.start":
                record.operation_name = event.name
                record.started_at = event.ts
            elif event.type == "operation.end":
                record.finished_at = event.ts
                record.status = "complete" if event.status == "ok" else "error"
                if event.status != "ok":
                    record.stop_reason = event.message or event.attrs.get("error") or event.name
            elif event.status == "error":
                if record.status != "complete":
                    record.status = "error"
                if record.stop_reason is None:
                    record.stop_reason = event.message or event.attrs.get("error") or event.name

    def record_checkpoint(self, session_id: str, run_id: str, checkpoint: RunCheckpoint) -> None:
        if not session_id or not run_id:
            return
        with self._lock:
            record = self._ensure_record(session_id, run_id)
            record.checkpoints.append(checkpoint)

    def finalize(
        self,
        session_id: str,
        run_id: str,
        *,
        status: str,
        stop_reason: str | None = None,
        finished_at: float | None = None,
    ) -> None:
        if not session_id or not run_id:
            return
        with self._lock:
            record = self._records.get((session_id, run_id))
            if record is None:
                return
            if finished_at is not None:
                record.finished_at = finished_at
            if record.status not in {"error", "complete"} or status == "error":
                record.status = status
            if stop_reason:
                record.stop_reason = stop_reason

    def get_run(self, session_id: str, run_id: str | None = None) -> RunRecord | None:
        with self._lock:
            key: tuple[str, str] | None
            if run_id is not None:
                key = (session_id, run_id)
            else:
                key = None
                for cand_session, cand_run in reversed(self._order):
                    if cand_session == session_id:
                        key = (cand_session, cand_run)
                        break
            if key is None:
                return None
            record = self._records.get(key)
            if record is None:
                return None
            return record.clone()


RUN_REPORT_STORE = RunReportStore(retention=_env_retention())


def start_run(
    session_id: str,
    run_id: str,
    *,
    tool_name: str | None,
    capability_stamp: str | None,
    started_at: float | None = None,
) -> None:
    """Register a run at request ingress."""

    RUN_REPORT_STORE.start_run(
        session_id,
        run_id,
        tool_name=tool_name,
        capability_stamp=capability_stamp,
        started_at=started_at,
    )


def finalize_run(
    session_id: str,
    run_id: str,
    *,
    status: str,
    stop_reason: str | None = None,
    finished_at: float | None = None,
) -> None:
    """Mark the run as complete/partial/error."""

    RUN_REPORT_STORE.finalize(
        session_id,
        run_id,
        status=status,
        stop_reason=stop_reason,
        finished_at=finished_at,
    )


def record_timeline_payload(payload: Mapping[str, Any]) -> None:
    """Subscribe to timeline events."""

    RUN_REPORT_STORE.record_event(coerce_event(payload))


def emit_checkpoint(
    stage: str,
    *,
    ok: bool,
    reason: str | None = None,
    **attrs: Any,
) -> None:
    """Capture a stage checkpoint tied to the current request."""

    session_id = current_session()
    run_id = current_run_id()
    if session_id is None or run_id is None:
        return
    RUN_REPORT_STORE.record_checkpoint(session_id, run_id, checkpoint_event(stage, ok=ok, reason=reason, **attrs))


def _build_operations(events: Sequence[TimelineEvent]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    op_stack: dict[str, TimelineEvent] = {}
    step_stack: dict[str, TimelineEvent] = {}
    for event in events:
        if event.type == "operation.start":
            op_stack[event.name] = event
        elif event.type == "operation.end":
            start = op_stack.pop(event.name, None)
            operations.append(
                {
                    "name": event.name,
                    "status": event.status,
                    "started_at": start.ts if start else None,
                    "finished_at": event.ts,
                    "duration_ms": event.attrs.get("duration_ms"),
                    "attrs": start.attrs if start else event.attrs,
                }
            )
        elif event.type == "step.start":
            step_stack[event.name] = event
        elif event.type == "step.end":
            start = step_stack.pop(event.name, None)
            steps.append(
                {
                    "name": event.name,
                    "status": event.status,
                    "started_at": start.ts if start else None,
                    "finished_at": event.ts,
                    "duration_ms": event.attrs.get("duration_ms"),
                    "attrs": event.attrs,
                }
            )
    return operations, steps


def _collect(events: Iterable[TimelineEvent], *, event_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for event in events:
        if event_type is not None and event.type != event_type:
            continue
        if status is not None and event.status != status:
            continue
        collected.append(
            {
                "ts": event.ts,
                "name": event.name,
                "type": event.type,
                "message": event.message,
                "attrs": event.attrs,
            }
        )
    return collected


def build_report(
    context: ApplicationContext,
    session_id: str,
    run_id: str | None = None,
) -> RunReport | None:
    """Build a run report for the provided session/run identifiers."""

    record = RUN_REPORT_STORE.get_run(session_id, run_id)
    if record is None:
        return None
    operations, steps = _build_operations(record.events)
    decisions = _collect(record.events, event_type="decision")
    warnings = [evt for evt in _collect(record.events) if evt["type"].endswith(".skip")]
    errors = _collect(record.events, status="error")
    checkpoints = [checkpoint.to_event_attrs() for checkpoint in record.checkpoints]
    timeline = [
        {
            "ts": event.ts,
            "type": event.type,
            "status": event.status,
            "name": event.name,
            "message": event.message,
            "attrs": event.attrs,
        }
        for event in record.events
    ]
    summary = {
        "tool": record.tool_name,
        "capability_stamp": record.capability_stamp,
        "duration_ms": (record.events[-1].attrs.get("duration_ms") if record.events else None),
    }
    capabilities = Capabilities.from_context(context).stamp({})
    return RunReport(
        session_id=record.session_id,
        run_id=record.run_id,
        status=record.status if record.status != "running" else "partial",
        stop_reason=record.stop_reason,
        started_at=record.started_at,
        finished_at=record.finished_at,
        operations=operations,
        steps=steps,
        decisions=decisions,
        warnings=warnings,
        errors=errors,
        checkpoints=checkpoints,
        timeline=timeline,
        summary=summary,
        capabilities=capabilities,
    )
