"""Trace-anchored flight recorder that mirrors run execution timelines."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeintel_rev.observability.semantic_conventions import Attrs
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_RECORDER_LOCK = threading.Lock()
_RECORDER_STATE: dict[str, object | None] = {"processor": None}


def _data_root() -> Path:
    """Return the base directory for diagnostic run artifacts.

    Returns
    -------
    Path
        Root directory where run reports are stored.
    """
    return Path(os.getenv("DATA_DIR", "data")).resolve() / "runs"


def _date_segment(start_ns: int | None) -> str:
    """Return the YYYYMMDD segment for a run report.

    Returns
    -------
    str
        Date segment used to partition run reports.
    """
    if start_ns is None:
        return datetime.now(UTC).strftime("%Y%m%d")
    seconds = start_ns / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y%m%d")


def _scrub_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"len": len(value)}
    if isinstance(value, Mapping):
        return {str(k): _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_scrub_value(item) for item in value]
    return str(value)


def _report_path(
    session_id: str | None,
    run_id: str | None,
    trace_id: str | None,
    started_ns: int | None,
    *,
    ensure_parent: bool,
) -> Path:
    """Return the filesystem path for a diagnostic run report.

    Returns
    -------
    Path
        Absolute path to the run report JSON file.
    """
    session = session_id or "anonymous"
    identifier = run_id or trace_id or "pending"
    base = _data_root() / _date_segment(started_ns) / session
    if ensure_parent:
        base.mkdir(parents=True, exist_ok=True)
    return base / f"{identifier}.json"


def build_report_uri(
    session_id: str | None,
    run_id: str | None,
    *,
    trace_id: str | None = None,
    started_at: float | None = None,
) -> str | None:
    """Return the expected diagnostic report path for the provided identifiers.

    Returns
    -------
    str | None
        Absolute path where the run report will be written, or ``None`` when
        insufficient identifiers are provided.
    """
    if session_id is None and run_id is None and trace_id is None:
        return None
    started_ns = None if started_at is None else int(started_at * 1_000_000_000)
    return str(_report_path(session_id, run_id, trace_id, started_ns, ensure_parent=False))


@dataclass(slots=True)
class _RunBuffer:
    session_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    root_span_id: str | None = None
    started_ns: int | None = None
    events: list[dict[str, object]] = field(default_factory=list)
    status: str = "ok"
    stop_reason: str | None = None
    diag_path: str | None = None


class _FlightRecorder:
    """Collect spans per-trace and emit ordered JSON reports."""

    def __init__(self) -> None:
        self._buffers: dict[str, _RunBuffer] = {}
        self._lock = threading.Lock()

    def on_start(self, span: object) -> None:
        trace_id = _trace_id(span)
        if trace_id is None:
            return
        with self._lock:
            buffer = self._buffers.setdefault(trace_id, _RunBuffer(trace_id=trace_id))
            start_ns = getattr(span, "start_time", None)
            if isinstance(start_ns, int):
                buffer.started_ns = buffer.started_ns or start_ns
            _update_identities(buffer, span)

    def on_end(self, span: object) -> None:
        trace_id = _trace_id(span)
        if trace_id is None:
            return
        event = _build_event(span)
        root_span = _is_root_span(span)
        with self._lock:
            buffer = self._buffers.setdefault(trace_id, _RunBuffer(trace_id=trace_id))
            buffer.events.append(event)
            buffer.root_span_id = buffer.root_span_id or event.get("span_id")
            _update_identities(buffer, span)
            _update_status(buffer, span, event)
            if root_span:
                self._flush_locked(trace_id, buffer)

    def shutdown(self) -> None:
        with self._lock:
            for trace_id, buffer in list(self._buffers.items()):
                self._flush_locked(trace_id, buffer)

    def _flush_locked(self, trace_id: str, buffer: _RunBuffer) -> None:
        self._buffers.pop(trace_id, None)
        path = _report_path(
            buffer.session_id,
            buffer.run_id,
            trace_id,
            buffer.started_ns,
            ensure_parent=True,
        )
        buffer.diag_path = str(path)
        payload = {
            "schema": "codeintel.flight-recorder@v1",
            "trace_id": trace_id,
            "span_id": buffer.root_span_id,
            "session_id": buffer.session_id,
            "run_id": buffer.run_id or trace_id,
            "status": buffer.status,
            "stop_reason": buffer.stop_reason,
            "events": sorted(buffer.events, key=lambda evt: evt.get("start_ns", 0)),
        }
        for evt in payload["events"]:
            start_ns = evt.pop("start_ns", None)
            end_ns = evt.pop("end_ns", None)
            evt["ts"] = _ts(start_ns)
            if start_ns is not None and end_ns is not None:
                evt["duration_ms"] = round((end_ns - start_ns) / 1_000_000, 3)
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:  # pragma: no cover - defensive
            LOGGER.warning("Failed to persist flight recorder output", exc_info=True)


class FlightRecorderSpanProcessor:
    """Minimal SpanProcessor-compatible shim."""

    def __init__(self, recorder: _FlightRecorder) -> None:
        self._recorder = recorder

    def on_start(self, span: object, parent_context: object | None = None) -> None:
        """Record span start events."""
        del parent_context
        self._recorder.on_start(span)

    def on_end(self, span: object) -> None:
        """Record span completion events."""
        self._recorder.on_end(span)

    def shutdown(self) -> None:
        """Flush any buffered traces before shutdown."""
        self._recorder.shutdown()

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """No-op flush hook required by the SpanProcessor protocol.

        Returns
        -------
        bool
            Always ``True``.
        """
        _ = self._recorder
        del timeout_millis
        return True


def install_flight_recorder(provider: object | None) -> None:
    """Attach the flight recorder span processor exactly once."""
    if provider is None:
        return
    with _RECORDER_LOCK:
        if _RECORDER_STATE["processor"] is not None:
            return
        recorder = _FlightRecorder()
        processor = FlightRecorderSpanProcessor(recorder)
        adder = getattr(provider, "add_span_processor", None)
        if adder is None:
            return
        try:
            adder(processor)
        except (RuntimeError, ValueError):  # pragma: no cover - defensive
            LOGGER.debug("Unable to register flight recorder span processor", exc_info=True)
            return
        _RECORDER_STATE["processor"] = processor


def _trace_id(span: object) -> str | None:
    ctx = getattr(span, "context", lambda: None)()
    if ctx is None:
        return None
    trace_id = getattr(ctx, "trace_id", 0)
    if not trace_id:
        return None
    return f"{int(trace_id):032x}"


def _span_id(span: object) -> str | None:
    ctx = getattr(span, "context", lambda: None)()
    if ctx is None:
        return None
    span_id = getattr(ctx, "span_id", 0)
    if not span_id:
        return None
    return f"{int(span_id):016x}"


def _update_identities(buffer: _RunBuffer, span: object) -> None:
    attrs = getattr(span, "attributes", {}) or {}
    session = attrs.get(Attrs.SESSION_ID)
    run_id = attrs.get(Attrs.RUN_ID)
    if isinstance(session, str):
        buffer.session_id = buffer.session_id or session
    if isinstance(run_id, str):
        buffer.run_id = buffer.run_id or run_id


def _update_status(buffer: _RunBuffer, span: object, event: Mapping[str, Any]) -> None:
    status_obj = getattr(span, "status", None)
    status_code = getattr(status_obj, "status_code", None)
    description = getattr(status_obj, "description", None)
    if getattr(status_code, "name", "") == "ERROR":
        buffer.status = "error"
        buffer.stop_reason = description or event.get("name")
    for evt in event.get("events", []):
        if evt.get("name") == "exception":
            buffer.status = "error"
            message = evt.get("attrs", {}).get("exception.message")
            buffer.stop_reason = buffer.stop_reason or message or evt.get("name")


def _is_root_span(span: object) -> bool:
    parent = getattr(span, "parent", None)
    if parent is None:
        return True
    span_id = getattr(parent, "span_id", 0)
    return not span_id


def _build_event(span: object) -> dict[str, Any]:
    attrs = dict(getattr(span, "attributes", {}) or {})
    start_ns = getattr(span, "start_time", None)
    end_ns = getattr(span, "end_time", None)
    status_obj = getattr(span, "status", None)
    status_code = getattr(status_obj, "status_code", None)
    status = getattr(status_code, "name", None) or "UNSET"
    payload = {
        "name": getattr(span, "name", ""),
        "stage": attrs.get(Attrs.STAGE) or attrs.get("stage"),
        "component": attrs.get(Attrs.COMPONENT) or attrs.get("component"),
        "status": status,
        "attrs": {str(key): _scrub_value(val) for key, val in attrs.items()},
        "events": _convert_span_events(getattr(span, "events", []) or []),
        "span_id": _span_id(span),
        "start_ns": start_ns,
        "end_ns": end_ns,
    }
    warn_flag = attrs.get(Attrs.WARN_DEGRADED)
    if warn_flag:
        payload.setdefault("warnings", []).append("degraded")
    return payload


def _convert_span_events(events: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "name": getattr(event, "name", ""),
            "ts": _ts(getattr(event, "timestamp", None)),
            "attrs": {
                str(key): _scrub_value(val)
                for key, val in (getattr(event, "attributes", {}) or {}).items()
            },
        }
        for event in events
    ]


def _ts(nanoseconds: int | None) -> str | None:
    if nanoseconds is None:
        return None
    seconds = nanoseconds / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
