"""Timeline-based run report builder and CLI helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeintel_rev.observability.timeline import Timeline

_RUN_REPORT_SCHEMA = "codeintel.telemetry/run-report@v0"
_RUN_OUTPUT_DIR = Path("data/observability/runs")
_LATEST_REPORT_STATE: dict[str, dict[str, object] | None] = {"value": None}


@dataclass(slots=True, frozen=True)
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


def _ensure_runs_dir(out_dir: Path | None) -> Path:
    target = (out_dir or _RUN_OUTPUT_DIR).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def render_run_report(timeline: Timeline, out_dir: Path | None = None) -> Path:
    """Render Markdown + JSON artifacts for the provided timeline.

    Parameters
    ----------
    timeline : Timeline
        Timeline instance containing events to render. The timeline must be
        sampled (timeline.sampled == True) or this function will raise
        RuntimeError.
    out_dir : Path | None, optional
        Optional output directory for report artifacts (default: None). When
        None, uses the default runs directory. The directory is created if
        it doesn't exist.

    Returns
    -------
    Path
        Path to the generated Markdown report file. The report is written to
        {out_dir}/{run_id}.md, with a corresponding JSON file at
        {out_dir}/{run_id}.json.

    Raises
    ------
    RuntimeError
        Raised when the timeline is not sampled (timeline.sampled == False).
        Only sampled timelines can be rendered as run reports.

    Notes
    -----
    This function generates both Markdown and JSON artifacts for the timeline.
    The Markdown report is human-readable and includes event summaries, while
    the JSON report contains the full event data for programmatic processing.
    The report metadata is also stored globally for retrieval via
    latest_run_report().
    """
    if not timeline.sampled:
        msg = "Cannot render run report for an unsampled timeline."
        raise RuntimeError(msg)
    events = timeline.snapshot()
    summary, first_error = _summarize_events(events) if events else ({"status": "empty"}, None)
    report_payload: dict[str, Any] = {
        "schema": _RUN_REPORT_SCHEMA,
        "kind": str(timeline.metadata.get("kind", "unknown")),
        "session": {
            "session_id": timeline.session_id,
            "started_at": timeline.metadata.get("started_at"),
        },
        "run": {
            "run_id": timeline.run_id,
        },
        "events": events,
        "summary": summary,
        "first_error": first_error,
        "metadata": dict(timeline.metadata),
    }
    out_path = _ensure_runs_dir(out_dir)
    json_path = out_path / f"{timeline.run_id}.json"
    json_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    markdown_path = out_path / f"{timeline.run_id}.md"
    markdown_path.write_text(_render_markdown_report(report_payload), encoding="utf-8")
    _LATEST_REPORT_STATE["value"] = {
        "markdown": str(markdown_path),
        "json": str(json_path),
        "session_id": timeline.session_id,
        "run_id": timeline.run_id,
        "summary": summary,
    }
    return markdown_path


def latest_run_report() -> dict[str, object] | None:
    """Return metadata for the most recently rendered run report.

    Returns
    -------
    dict[str, object] | None
        Dictionary containing the most recent run report metadata, or None
        if no report has been rendered yet. The dictionary includes keys:
        "markdown" (str path), "json" (str path), "session_id", "run_id", and
        "summary". Returns None when no reports have been generated.
    """
    return _LATEST_REPORT_STATE["value"]


def build_timeline_run_report(
    *,
    session_id: str,
    run_id: str | None = None,
    timeline_dir: Path | None = None,
) -> TimelineRunReport:
    """Build a run report by parsing Timeline JSONL artifacts.

    This function constructs a TimelineRunReport by loading and parsing Timeline
    JSONL event files from the timeline directory. The function resolves the
    timeline directory, loads events for the specified session and optional run,
    and builds a structured report containing all events.

    Parameters
    ----------
    session_id : str
        Session identifier to load events for. Used to identify the Timeline
        session directory and filter events. Must match a session directory
        in the timeline root.
    run_id : str | None, optional
        Optional run identifier to filter events for a specific run (default: None).
        When None, loads all events for the session. When provided, filters
        events to only those matching the run_id.
    timeline_dir : Path | None, optional
        Optional timeline root directory path (default: None). When None, uses
        the default timeline directory from environment or configuration.
        Used to locate Timeline JSONL artifact files.

    Returns
    -------
    TimelineRunReport
        Structured run summary derived from Timeline records. The report contains
        session_id, run_id, and a list of parsed events. Returns an empty report
        with no events when no matching Timeline files are found.
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


def _render_markdown_report(payload: Mapping[str, Any]) -> str:
    lines: list[str] = [
        f"# Run Report — `{payload['run']['run_id']}`",
        f"- **Session:** `{payload['session']['session_id']}`",
        f"- **Status:** **{payload['summary']['status']}**",
        f"- **Events Recorded:** {len(payload['events'])}",
    ]
    first_error = payload.get("first_error")
    if first_error:
        message = first_error.get("message") or ""
        lines.append(
            f"- **First Error:** `{first_error.get('name')}` {message}".strip(),
        )
    lines.extend(
        [
            "",
            "## Timeline",
        ]
    )
    for event in payload["events"]:
        ts = datetime.fromtimestamp(event.get("ts", 0.0), tz=UTC).isoformat()
        attrs = event.get("attrs") or {}
        attr_text = ", ".join(f"{k}={v}" for k, v in attrs.items())
        line = (
            f"- `{ts}` `{event.get('type')}` **{event.get('name')}** status=`{event.get('status')}`"
        )
        if attr_text:
            line += f" ({attr_text})"
        if event.get("message"):
            line += f" — {event['message']}"
        lines.append(line)
    decisions = [evt for evt in payload["events"] if evt.get("type") == "decision"]
    if decisions:
        lines.append("")
        lines.append("## Decisions")
        for evt in decisions:
            attrs = evt.get("attrs") or {}
            reason = attrs.get("reason") or ""
            lines.append(
                f"- `{evt.get('name')}` reason=`{reason}` attrs={json.dumps(attrs, sort_keys=True)}"
            )
    return "\n".join(lines)
