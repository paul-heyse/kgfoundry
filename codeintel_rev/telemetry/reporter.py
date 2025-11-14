"""In-memory run report builder fed by timeline events."""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.diagnostics.detectors import detect
from codeintel_rev.metrics.registry import MCP_RUN_ERRORS_TOTAL, MCP_RUNS_TOTAL
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.telemetry.context import (
    current_run_id,
    current_session,
)
from codeintel_rev.telemetry.events import (
    RunCheckpoint,
    TimelineEvent,
    checkpoint_event,
    coerce_event,
)

__all__ = [
    "RUN_REPORT_STORE",
    "RunReport",
    "RunReportStore",
    "RunReportV2",
    "build_report",
    "build_run_report_v2",
    "emit_checkpoint",
    "finalize_run",
    "record_step_payload",
    "record_timeline_payload",
    "render_markdown",
    "render_markdown_v2",
    "render_mermaid",
    "report_to_json",
    "start_run",
]


def _env_retention() -> int:
    raw = os.getenv("RUN_REPORT_RETENTION", "100").strip()
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(10, min(5000, value))


def _infer_stop_reason_from_events(events: Sequence[Mapping[str, Any]]) -> str | None:
    last_reason: str | None = None
    for payload in events:
        status = str(payload.get("status") or "").lower()
        if status not in {"failed", "timed_out"}:
            continue
        kind = str(
            payload.get("kind") or payload.get("op") or payload.get("component") or "unknown"
        )
        detail = payload.get("detail")
        last_reason = f"{kind}:{detail}" if detail else f"{kind}:{status}"
    return last_reason


def _default_budget_snapshot(context: ApplicationContext) -> dict[str, object]:
    snapshot: dict[str, object] = {"rrf_k": 60}
    settings = getattr(context, "settings", None)
    if settings is None:
        return snapshot
    index_cfg = getattr(settings, "index", None)
    if index_cfg is not None:
        snapshot["rrf_k"] = getattr(index_cfg, "rrf_k", snapshot["rrf_k"])
        prefetch = getattr(index_cfg, "hybrid_prefetch", {})
        if isinstance(prefetch, Mapping):
            snapshot["per_channel_depths"] = dict(prefetch)
    bm25_cfg = getattr(settings, "bm25", None)
    if bm25_cfg is not None:
        snapshot["rm3_enabled"] = bool(getattr(bm25_cfg, "rm3_enabled", False))
    return snapshot


def _checkpoint_hit(
    checkpoints: Sequence[Mapping[str, Any]],
    prefixes: tuple[str, ...],
) -> bool:
    for checkpoint in checkpoints:
        stage = checkpoint.get("stage")
        if not isinstance(stage, str):
            continue
        if any(stage.startswith(prefix) for prefix in prefixes):
            return True
    return False


def _checkpoint_summaries(checkpoints: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        stage = checkpoint.get("stage")
        if not isinstance(stage, str):
            continue
        attrs = dict(checkpoint)
        ok = bool(attrs.pop("ok", False))
        reason = attrs.pop("reason", None)
        attrs.pop("stage", None)
        summaries.append(
            {
                "name": stage,
                "ok": ok,
                "reason": reason,
                "attrs": attrs,
            }
        )
    return summaries


def _compute_ops_coverage(checkpoints: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    return {
        "embed": _checkpoint_hit(checkpoints, ("search.embed", "coderank.embed")),
        "dense": _checkpoint_hit(checkpoints, ("search.faiss", "coderank.faiss")),
        "sparse": _checkpoint_hit(checkpoints, ("search.bm25", "search.splade")),
        "gather": _checkpoint_hit(
            checkpoints,
            ("gather.channels", "search.bm25", "search.splade"),
        ),
        "fuse": _checkpoint_hit(
            checkpoints,
            ("search.rrf_fuse", "fusion.rrf", "fusion.pool"),
        ),
        "hydrate": _checkpoint_hit(checkpoints, ("hydrate.",)),
    }


_STAGE_SEQUENCE: list[tuple[str, str]] = [
    ("retrieval.gather_channels", "gather"),
    ("retrieval.fuse", "fuse"),
    ("duckdb.query", "hydrate"),
    ("retrieval.rerank", "rerank"),
]


def _normalize_stage_event(kind: str | None) -> str | None:
    """Normalize event kind to a stage label.

    This function maps event kind strings to normalized stage labels used in
    run reports. It is called during stage summary construction to identify
    which stage an event belongs to. Used by telemetry reporting to group
    events by retrieval stage.

    Parameters
    ----------
    kind : str | None
        Event kind string to normalize, or None.

    Returns
    -------
    str | None
        Normalized stage label (e.g., "gather", "fuse", "hydrate", "rerank"),
        or None if the kind does not match any known stage.
    """
    if not kind:
        return None
    if kind.startswith("duckdb."):
        return "hydrate"
    for event_name, label in _STAGE_SEQUENCE:
        if kind == event_name:
            return label
    return None


def _build_stage_summary(record: RunRecord) -> tuple[list[RunReportStage], str | None]:
    """Return ordered stage summaries and the last completed stage.

    Parameters
    ----------
    record : RunRecord
        Run record containing structured step events.

    Returns
    -------
    tuple[list[RunReportStage], str | None]
        Ordered stage summaries alongside the name of the last completed stage,
        or ``None`` when no stage completed.
    """
    stage_map: dict[str, Mapping[str, Any]] = {}
    for event in record.structured_events:
        stage_label = _normalize_stage_event(event.get("kind"))
        if stage_label is None or stage_label in stage_map:
            continue
        stage_map[stage_label] = event
    stages: list[RunReportStage] = []
    last_completed: str | None = None
    for _, label in _STAGE_SEQUENCE:
        event = stage_map.get(label)
        if event is None:
            stages.append(
                RunReportStage(
                    name=label,
                    status="pending",
                    detail=None,
                    ts=None,
                    duration_ms=None,
                    payload=None,
                    trace_id=None,
                    span_id=None,
                )
            )
            continue
        status = str(event.get("status") or "unknown")
        detail = event.get("detail")
        payload = event.get("payload")
        payload_dict = dict(payload) if isinstance(payload, Mapping) else None
        duration = None
        if payload_dict is not None:
            duration = payload_dict.get("duration_ms")
            if isinstance(duration, str):
                try:
                    duration = float(duration)
                except ValueError:
                    duration = None
        stage_ts_raw = event.get("ts")
        stage_ts = str(stage_ts_raw) if stage_ts_raw is not None else None
        trace_id = event.get("trace_id")
        span_id = event.get("span_id")
        if status == "completed":
            last_completed = label
        stages.append(
            RunReportStage(
                name=label,
                status=status,
                detail=detail,
                ts=stage_ts,
                duration_ms=duration if isinstance(duration, (int, float)) else None,
                payload=payload_dict,
                trace_id=str(trace_id) if trace_id else None,
                span_id=str(span_id) if span_id else None,
            )
        )
    return stages, last_completed


def _budgets_from_timeline(
    events: Sequence[Mapping[str, Any]],
    structured_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") != "decision":
            continue
        name = str(event.get("name") or "")
        if name not in {"gate.budget", "retrieval.budget"}:
            continue
        attrs = event.get("attrs")
        if isinstance(attrs, Mapping):
            return dict(attrs)
    if structured_events is None:
        return None
    for record in structured_events:
        if record.get("kind") != "retrieval.budget":
            continue
        payload = record.get("payload")
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


@dataclass(slots=True, frozen=False)
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
    metrics_recorded: bool = False
    structured_events: list[dict[str, Any]] = field(default_factory=list)

    def clone(self) -> RunRecord:
        """Return a shallow copy suitable for read-only processing.

        Returns
        -------
        RunRecord
            Independent copy of this record.
        """
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
            structured_events=list(self.structured_events),
        )


@dataclass(slots=True, frozen=True)
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
    structured_events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        Returns
        -------
        dict[str, Any]
            Dictionary containing all report fields.
        """
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
            "structured_events": self.structured_events,
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
        """Register or update the metadata for a run record."""
        with self._lock:
            record = self._ensure_record(session_id, run_id)
            record.tool_name = tool_name
            record.capability_stamp = capability_stamp
            record.started_at = record.started_at or started_at

    def record_event(self, event: TimelineEvent) -> None:
        """Append a timeline event to the stored history."""
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
        """Persist a structured checkpoint emitted by decorators."""
        if not session_id or not run_id:
            return
        with self._lock:
            record = self._ensure_record(session_id, run_id)
            record.checkpoints.append(checkpoint)

    def record_structured_event(self, payload: Mapping[str, Any]) -> None:
        """Record structured telemetry payloads for the given run."""
        session_id = str(payload.get("session_id") or "")
        run_id = str(payload.get("run_id") or "")
        if not session_id or not run_id:
            return
        with self._lock:
            record = self._ensure_record(session_id, run_id)
            record.structured_events.append(dict(payload))

    def finalize(
        self,
        session_id: str,
        run_id: str,
        *,
        status: str,
        stop_reason: str | None = None,
        finished_at: float | None = None,
    ) -> None:
        """Finish a run and emit metrics once."""
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
            if record.stop_reason is None:
                inferred_reason = _infer_stop_reason_from_events(record.structured_events)
                if inferred_reason:
                    record.stop_reason = inferred_reason
            if not record.metrics_recorded and record.status in {"complete", "error", "partial"}:
                tool = record.tool_name or "unknown"
                MCP_RUNS_TOTAL.labels(tool=tool, status=record.status).inc()
                if record.status == "error":
                    code = (record.stop_reason or "unknown").split(":")[0].strip() or "unknown"
                    MCP_RUN_ERRORS_TOTAL.labels(tool=tool, error_code=code).inc()
                record.metrics_recorded = True

    def get_run(self, session_id: str, run_id: str | None = None) -> RunRecord | None:
        """Return a cloned run record for the session/run combination.

        This method retrieves a run record from the store for the specified session
        and optional run identifier. When run_id is None, returns the most recent
        run for the session. The returned record is a shallow copy to prevent
        external modifications.

        Parameters
        ----------
        session_id : str
            Session identifier to search for. Used to filter run records by session.
            The method searches for runs associated with this session.
        run_id : str | None, optional
            Optional run identifier to retrieve a specific run (default: None).
            When None, returns the most recent run for the session by searching
            the order deque in reverse. When provided, retrieves the exact run
            matching both session_id and run_id.

        Returns
        -------
        RunRecord | None
            Shallow copy of the stored run record, or None when no matching run
            is found. The record contains events, checkpoints, and metadata for
            the requested run.
        """
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


def record_step_payload(payload: Mapping[str, Any]) -> None:
    """Record structured step events for inclusion in run reports."""
    RUN_REPORT_STORE.record_structured_event(payload)


def emit_checkpoint(
    stage: str,
    *,
    ok: bool,
    reason: str | None = None,
    **attrs: object,
) -> None:
    """Capture a stage checkpoint tied to the current request."""
    session_id = current_session()
    run_id = current_run_id()
    if session_id is None or run_id is None:
        return
    RUN_REPORT_STORE.record_checkpoint(
        session_id, run_id, checkpoint_event(stage, ok=ok, reason=reason, **attrs)
    )


def _build_operations(
    events: Sequence[TimelineEvent],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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


def _collect(
    events: Iterable[TimelineEvent], *, event_type: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
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
    """Build a run report for the provided session/run identifiers.

    This function aggregates telemetry data from stored run records and builds
    a comprehensive RunReport containing operations, steps, decisions, warnings,
    errors, and checkpoints. The function retrieves the run record from the
    store and processes events to generate the report.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing runtime configuration and state. Used to
        access application metadata and configuration for the report. The context
        provides information about the application instance that generated the run.
    session_id : str
        Session identifier to retrieve run data for. Used to identify the
        telemetry session containing the run report. Must match a session in
        the run report store.
    run_id : str | None, optional
        Optional run identifier to retrieve a specific run report (default: None).
        When None, retrieves the most recent run for the session. When provided,
        retrieves the exact run matching both session_id and run_id.

    Returns
    -------
    RunReport | None
        Aggregated run report containing operations, steps, decisions, warnings,
        errors, and checkpoints, or None when no matching run data exists in
        the store. The report is suitable for serialization and display.
    """
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
        "budgets": _default_budget_snapshot(context),
    }
    capabilities_obj = Capabilities.from_context(context)
    capabilities_payload = capabilities_obj.model_dump()
    capabilities_payload["stamp"] = capabilities_obj.stamp(capabilities_payload.copy())
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
        capabilities=capabilities_payload,
        structured_events=list(record.structured_events),
    )


def build_run_report_v2(
    session_id: str,
    run_id: str | None = None,
) -> RunReportV2 | None:
    """Return a compact stage-centric report for ``session_id``/``run_id``.

    Parameters
    ----------
    session_id : str
        Session identifier to summarize.
    run_id : str | None, optional
        Specific run identifier. When ``None``, the most recent run is used.

    Returns
    -------
    RunReportV2 | None
        Compact run summary when available, otherwise ``None``.
    """
    record = RUN_REPORT_STORE.get_run(session_id, run_id)
    if record is None:
        return None
    stages, stopped_after = _build_stage_summary(record)
    warnings = [
        str(event.get("detail"))
        for event in record.structured_events
        if event.get("detail") and event.get("status") in {"degraded", "failed"}
    ]
    trace_id = next(
        (str(event.get("trace_id")) for event in record.structured_events if event.get("trace_id")),
        None,
    )
    if not trace_id:
        trace_id = record.run_id
    timeline_entries = [
        {
            "ts": event.ts,
            "type": event.type,
            "name": event.name,
            "status": event.status,
            "message": event.message,
            "attrs": dict(event.attrs),
        }
        for event in record.events
    ]
    structured_events = [
        {
            "ts": event.get("ts"),
            "kind": event.get("kind"),
            "status": event.get("status"),
            "detail": event.get("detail"),
            "payload": event.get("payload"),
            "trace_id": event.get("trace_id"),
            "span_id": event.get("span_id"),
        }
        for event in record.structured_events
    ]
    budgets = _budgets_from_timeline(timeline_entries, record.structured_events)
    stopped_because = record.stop_reason or (
        f"stage:{stopped_after}" if stopped_after else None
    )
    span_attributes: dict[str, object] = {
        Attrs.MCP_SESSION_ID: record.session_id,
        Attrs.MCP_RUN_ID: record.run_id,
    }
    if record.tool_name:
        span_attributes[Attrs.MCP_TOOL] = record.tool_name
    if record.capability_stamp:
        span_attributes["capability_stamp"] = record.capability_stamp
    # Remove None values for serialization clarity
    span_attributes = {key: value for key, value in span_attributes.items() if value is not None}
    return RunReportV2(
        trace_id=trace_id,
        session_id=record.session_id,
        run_id=record.run_id,
        tool=record.tool_name,
        stages=stages,
        timeline=timeline_entries,
        events=structured_events,
        warnings=warnings,
        budgets=budgets,
        stopped_after_stage=stopped_after,
        stopped_because=stopped_because,
        span_attributes=span_attributes,
    )


def report_to_json(report: RunReport) -> dict[str, Any]:
    """Return JSON-serializable payload for the report.

    This function converts a RunReport object into a JSON-serializable dictionary
    by calling the report's to_dict() method. The resulting dictionary can be
    serialized to JSON for API responses or storage.

    Parameters
    ----------
    report : RunReport
        Run report object to convert to JSON format. The report contains
        operations, steps, decisions, warnings, errors, and checkpoints that
        are serialized into the dictionary.

    Returns
    -------
    dict[str, Any]
        JSON-ready dictionary representation of the report. The dictionary
        contains all report fields in a format suitable for JSON serialization.
        Can be used with json.dumps() or FastAPI JSONResponse.
    """
    payload = report.to_dict()
    payload.setdefault("trace_id", report.run_id)
    checkpoints = payload.get("checkpoints")
    if isinstance(checkpoints, Sequence):
        checkpoint_items = [cp for cp in checkpoints if isinstance(cp, Mapping)]
    else:
        checkpoint_items = []
    payload["ops_coverage"] = _compute_ops_coverage(checkpoint_items)
    payload["stages"] = _checkpoint_summaries(checkpoint_items)
    timeline_events = payload.get("timeline")
    if isinstance(timeline_events, Sequence):
        filtered_events = [event for event in timeline_events if isinstance(event, Mapping)]
    else:
        filtered_events = []
    structured_events = [event for event in report.structured_events if isinstance(event, Mapping)]
    budgets = _budgets_from_timeline(filtered_events, structured_events)
    summary_budgets = payload.get("summary", {}).get("budgets")
    fallback_budgets = dict(summary_budgets) if isinstance(summary_budgets, Mapping) else {}
    if budgets:
        payload["budgets"] = budgets
    else:
        payload["budgets"] = fallback_budgets
    try:
        payload["hints"] = detect(payload)
    except (RuntimeError, ValueError, TypeError):  # pragma: no cover - defensive
        payload["hints"] = []
    return payload


@dataclass(slots=True, frozen=True)
class RunReportStage:
    """Normalized stage summary for RunReportV2."""

    name: str
    status: str
    detail: str | None
    ts: str | None
    duration_ms: float | None
    payload: Mapping[str, Any] | None
    trace_id: str | None
    span_id: str | None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the stage.

        Returns
        -------
        dict[str, object]
            Stage summary payload.
        """
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "ts": self.ts,
            "duration_ms": self.duration_ms,
            "payload": dict(self.payload) if self.payload else None,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


@dataclass(slots=True, frozen=True)
class RunReportV2:
    """Compact narrative describing key retrieval stages."""

    trace_id: str | None
    session_id: str | None
    run_id: str
    tool: str | None
    stages: list[RunReportStage]
    timeline: list[dict[str, Any]]
    events: list[dict[str, Any]]
    warnings: list[str]
    budgets: Mapping[str, Any] | None
    stopped_after_stage: str | None
    stopped_because: str | None
    span_attributes: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable payload for the V2 report.

        Returns
        -------
        dict[str, object]
            Serialized report dictionary.
        """
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "tool": self.tool,
            "stages": [stage.as_dict() for stage in self.stages],
            "timeline": list(self.timeline),
            "events": list(self.events),
            "warnings": list(self.warnings),
            "budgets": dict(self.budgets) if self.budgets else None,
            "stopped_after_stage": self.stopped_after_stage,
            "stopped_because": self.stopped_because,
            "span_attributes": dict(self.span_attributes),
        }


def render_mermaid(report: RunReport) -> str:
    """Return a Mermaid graph describing stage checkpoints.

    This function renders a run report as a Mermaid flowchart diagram showing
    the sequence of stage checkpoints and their status. It is called by HTTP
    endpoints and CLI commands to visualize run execution flow.

    Parameters
    ----------
    report : RunReport
        Run report containing checkpoint data to visualize.

    Returns
    -------
    str
        Mermaid ``graph TD`` describing the run's checkpoints with node labels
        showing stage names, status (OK/FAILED), and optional reason messages.
    """
    checkpoints = report.checkpoints
    lines = ["graph TD"]
    if not checkpoints:
        lines.append('empty["No checkpoints recorded"]')
        return "\n".join(lines)
    node_ids: list[str] = []
    for idx, checkpoint in enumerate(checkpoints, 1):
        stage = checkpoint.get("stage") or f"stage_{idx}"
        status = "OK" if checkpoint.get("ok") else "FAILED"
        reason = checkpoint.get("reason")
        reason_suffix = f"\\n{reason}" if reason else ""
        node_id = f"stage{idx}"
        label = f"{stage}\\n{status}{reason_suffix}"
        lines.append(f'{node_id}["{label}"]')
        node_ids.append(node_id)
    for prev, current in pairwise(node_ids):
        lines.append(f"{prev} --> {current}")
    return "\n".join(lines)


def render_markdown(report: RunReport) -> str:
    """Render the report as Markdown.

    This function converts a RunReport object into a human-readable Markdown
    string. The function formats operations, steps, decisions, warnings, errors,
    and checkpoints into structured Markdown sections suitable for display in
    documentation or web interfaces.

    Parameters
    ----------
    report : RunReport
        Run report object to render as Markdown. The report contains telemetry
        data, metrics, and execution details that are formatted into Markdown
        sections with headers, lists, and tables.

    Returns
    -------
    str
        Markdown-formatted summary string containing all report sections.
        The string includes headers, lists, and formatted data suitable for
        rendering in Markdown viewers or conversion to HTML.
    """

    def _append_section(title: str, entries: list[str]) -> None:
        if not entries:
            return
        lines.append(f"## {title}")
        lines.extend(entries)

    lines: list[str] = [
        f"# Run report — session `{report.session_id}`",
        f"- **Run ID:** `{report.run_id}`",
        f"- **Status:** **{report.status}**",
    ]
    if report.stop_reason:
        lines.append(f"- **Stop reason:** {report.stop_reason}")
    lines.extend(
        [
            "",
            "## Capabilities",
            "```json",
            json.dumps(report.capabilities, indent=2),
            "```",
        ]
    )
    _append_section(
        "Operations",
        [
            f"- `{op['name']}` status=`{op['status']}` duration={op.get('duration_ms')}ms attrs={op.get('attrs')}"
            for op in report.operations
        ],
    )
    _append_section(
        "Steps",
        [
            f"- `{step['name']}` ({step['status']}) duration={step.get('duration_ms')}ms attrs={step.get('attrs')}"
            for step in report.steps
        ],
    )
    _append_section(
        "Checkpoints",
        [
            f"- `{checkpoint['stage']}` — {'ok' if checkpoint.get('ok') else 'error'} {checkpoint.get('reason') or ''}"
            for checkpoint in report.checkpoints
        ],
    )
    _append_section(
        "Errors",
        [f"- `{err['name']}`: {err.get('message', '')}" for err in report.errors],
    )
    _append_section(
        "Warnings",
        [f"- `{warning['name']}`: {warning.get('message', '')}" for warning in report.warnings],
    )
    return "\n".join(lines)


def render_markdown_v2(report: RunReportV2) -> str:
    """Render a RunReportV2 payload as Markdown text.

    This function formats a compact stage-centric run report as Markdown suitable
    for display in documentation or web interfaces. It is called by HTTP endpoints
    and CLI commands to provide human-readable run summaries.

    Parameters
    ----------
    report : RunReportV2
        Compact run report containing stages, warnings, and metadata.

    Returns
    -------
    str
        Markdown-formatted representation of the V2 report including run ID,
        trace ID, session ID, stage summaries, and warnings.
    """
    lines = [
        f"# Run {report.run_id}",
        f"- Tool: {report.tool or 'n/a'}",
        f"- Trace ID: {report.trace_id or 'n/a'}",
        f"- Session ID: {report.session_id or 'n/a'}",
    ]
    if report.stopped_because:
        lines.append(f"- Stopped because: {report.stopped_because}")
    elif report.stopped_after_stage:
        lines.append(f"- Stopped after stage: `{report.stopped_after_stage}`")
    if report.budgets:
        lines.extend(
            [
                "",
                "## Budgets",
                "```json",
                json.dumps(report.budgets, indent=2, ensure_ascii=False),
                "```",
            ]
        )
    lines.append("")
    lines.append("## Stages")
    for stage in report.stages:
        detail_suffix = f" — {stage.detail}" if stage.detail else ""
        duration_suffix = (
            f" ({stage.duration_ms:.2f} ms)" if isinstance(stage.duration_ms, (int, float)) else ""
        )
        lines.append(f"- **{stage.name}**: {stage.status}{detail_suffix}{duration_suffix}")
    if report.timeline:
        lines.append("")
        lines.append("## Timeline")
        for entry in report.timeline:
            timestamp = entry.get("ts")
            ts_display = f"{timestamp:.3f}s" if isinstance(timestamp, (int, float)) else timestamp
            lines.append(
                f"- [{ts_display}] {entry.get('type')} `{entry.get('name')}` → {entry.get('status')}"
            )
    if report.events:
        lines.append("")
        lines.append("## Discrete Events")
        for event in report.events:
            payload = event.get("payload")
            payload_suffix = f" payload={payload}" if payload else ""
            lines.append(
                f"- {event.get('kind')} ({event.get('status')}){payload_suffix}".strip()
            )
    if report.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.span_attributes:
        lines.append("")
        lines.append("## Span Attributes")
        lines.append("```json")
        lines.append(json.dumps(report.span_attributes, indent=2, ensure_ascii=False))
        lines.append("```")
    return "\n".join(lines)
