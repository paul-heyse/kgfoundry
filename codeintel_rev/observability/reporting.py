"""Timeline-based run report builder and CLI helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TimelineRunReport:
    """Structured summary derived from Timeline JSONL records."""

    session_id: str
    run_id: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    first_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the report.

        Returns
        -------
        dict[str, Any]
            Mapping suitable for JSON serialization.
        """
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "summary": self.summary,
            "first_error": self.first_error,
            "events": self.events,
        }


def build_timeline_run_report(
    *,
    session_id: str,
    run_id: str | None = None,
    timeline_dir: Path | None = None,
) -> TimelineRunReport:
    """Build a run report by parsing Timeline JSONL artifacts.

    Returns
    -------
    TimelineRunReport
        Structured run summary derived from Timeline records.
    """
    root = _resolve_timeline_dir(timeline_dir)
    events = _load_events(root, session_id, run_id)
    if not events:
        return TimelineRunReport(
            session_id=session_id,
            run_id=run_id,
            events=[],
            summary={"status": "missing", "events": 0},
            first_error=None,
        )
    events.sort(key=lambda evt: float(evt.get("ts", 0.0)))
    resolved_run_id = run_id or events[0].get("run_id")
    summary, first_error = _summarize_events(events)
    return TimelineRunReport(
        session_id=session_id,
        run_id=resolved_run_id,
        events=events,
        summary=summary,
        first_error=first_error,
    )


def _resolve_timeline_dir(candidate: Path | None) -> Path:
    if candidate is not None:
        return candidate.resolve()
    root = Path(os.getenv("CODEINTEL_DIAG_DIR", "./data/diagnostics")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_events(root: Path, session_id: str, run_id: str | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(root.glob("events-*.jsonl"), reverse=True):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("session_id") != session_id:
                        continue
                    if run_id is not None and payload.get("run_id") != run_id:
                        continue
                    events.append(payload)
        except FileNotFoundError:  # pragma: no cover - directory may be pruned concurrently
            continue
    return events


def _summarize_events(events: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    operations = [evt for evt in events if evt.get("type", "").startswith("operation")]
    steps = [evt for evt in events if evt.get("type", "").startswith("step")]
    decisions = [evt for evt in events if evt.get("type") == "decision"]
    first_error = next((evt for evt in events if evt.get("status") == "error"), None)
    status = "partial"
    if operations:
        last = operations[-1]
        if last.get("type") == "operation.end":
            status = "complete" if last.get("status") == "ok" else "error"
    channel_stats = _collect_channel_stats(events)
    summary = {
        "status": status,
        "events": len(events),
        "operations": len(operations),
        "steps": len(steps),
        "decisions": len(decisions),
        "channels": channel_stats,
    }
    return summary, first_error


def _collect_channel_stats(events: list[dict[str, Any]]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for event in events:
        name = event.get("name") or ""
        if not name.startswith("hybrid.") or not name.endswith(".run"):
            continue
        channel = name.split(".")[1]
        hits = event.get("attrs", {}).get("hits")
        try:
            stats[channel] = int(hits)
        except (TypeError, ValueError):
            continue
    return stats
