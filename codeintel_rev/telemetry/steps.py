"""Structured step event helpers."""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from codeintel_rev.observability.execution_ledger import record as ledger_record
from codeintel_rev.observability.ledger import RunLedger
from codeintel_rev.observability.runtime_observer import current_run_ledger
from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
from codeintel_rev.telemetry.context import current_run_id, current_session, current_stage
from codeintel_rev.telemetry.otel_shim import trace_api

LOGGER = logging.getLogger(__name__)
_REPORTER_STATE: dict[str, object | None] = {"initialized": False, "hook": None}

StepStatus = Literal["completed", "skipped", "failed", "timed_out", "degraded"]

__all__ = ["StepEvent", "StepStatus", "emit_step"]


@dataclass(slots=True, frozen=True)
class StepEvent:
    """Immutable representation of a discrete pipeline step."""

    kind: str
    status: StepStatus
    detail: str | None = None
    payload: Mapping[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def emit_step(step: StepEvent, *, ledger: RunLedger | None = None) -> None:
    """Emit a structured step event to the current sinks."""
    active_ledger = ledger or current_run_ledger()
    span = trace_api.get_current_span()
    span = span if span and span.is_recording() else None
    attrs: MutableMapping[str, Any] = {
        Attrs.STEP_KIND: step.kind,
        Attrs.STEP_STATUS: step.status,
    }
    if step.detail:
        attrs[Attrs.STEP_DETAIL] = step.detail
    if step.payload:
        attrs[Attrs.STEP_PAYLOAD] = to_label_str(step.payload)

    if span and span.is_recording():
        span.add_event("codeintel.step", attributes=dict(attrs))

    record = {
        "ts": _now_iso(),
        "trace_id": None,
        "span_id": None,
        "session_id": current_session(),
        "run_id": current_run_id(),
        **asdict(step),
    }
    if span:
        ctx = span.get_span_context()
        if ctx.trace_id:
            record["trace_id"] = f"{ctx.trace_id:032x}"
        if ctx.span_id:
            record["span_id"] = f"{ctx.span_id:016x}"
    ledger_ok = step.status in {"completed", "skipped"}
    ledger_attrs: dict[str, object] = {
        Attrs.STEP_KIND: step.kind,
        Attrs.STEP_STATUS: step.status,
    }
    if step.detail:
        ledger_attrs[Attrs.STEP_DETAIL] = step.detail
    if step.payload:
        ledger_attrs[Attrs.STEP_PAYLOAD] = to_label_str(step.payload)
    try:
        ledger_record(
            f"step.{step.kind}",
            stage=current_stage(),
            component="mcp.step",
            ok=ledger_ok,
            **ledger_attrs,
        )
    except Exception:  # pragma: no cover - telemetry mirroring best effort
        LOGGER.debug("Failed to mirror step event into execution ledger", exc_info=True)
    if active_ledger is not None:
        active_ledger.append(record)
    _record_structured_event(record)

    try:
        LOGGER.info("codeintel.step %s", json.dumps(record, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):  # pragma: no cover - defensive logging path
        LOGGER.debug("Failed to JSON encode step record", exc_info=True)


def _record_structured_event(record: dict[str, Any]) -> None:
    if not _REPORTER_STATE["initialized"]:
        try:  # pragma: no cover - optional dependency
            module = importlib.import_module("codeintel_rev.telemetry.reporter")
            hook = module.record_step_payload
        except (ImportError, AttributeError):
            _REPORTER_STATE["hook"] = None
        else:
            _REPORTER_STATE["hook"] = cast("Callable[[dict[str, Any]], None]", hook)
        _REPORTER_STATE["initialized"] = True
    hook = cast("Callable[[dict[str, Any]], None] | None", _REPORTER_STATE["hook"])
    if hook is None:
        return
    try:
        hook(record)
    except (RuntimeError, ValueError, TypeError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to forward structured step event", exc_info=True)
