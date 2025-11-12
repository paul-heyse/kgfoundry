"""CLI for rendering session timelines as Markdown diagnostics."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

GLYPHS = {"ok": "✅", "error": "❌", "skip": "⏭️"}
STAGE_EVENT_MAP = {
    "embed": "embed.end",
    "faiss.search": "faiss.search.end",
    "hybrid.fuse": "hybrid.fuse.end",
    "duckdb.hydrate": "duckdb.hydrate.end",
}
HASH_PREVIEW_LEN = 16


def _load_events(path: Path, session: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("session_id") == session:
                events.append(event)
    return events


def _group_events_by_run(
    events: Iterable[dict[str, Any]],
) -> dict[str | None, list[dict[str, Any]]]:
    grouped: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event.get("run_id")].append(event)
    return grouped


def _select_run_events(events: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    grouped = _group_events_by_run(events)
    if not grouped:
        return None, []

    def _last_ts(items: list[dict[str, Any]]) -> float:
        return max((evt.get("ts") or 0.0) for evt in items)

    run_id, run_events = max(grouped.items(), key=lambda item: _last_ts(item[1]))
    run_events.sort(key=lambda evt: evt.get("ts", 0))
    return run_id, run_events


def _format_attrs(attrs: dict[str, Any], keys: Iterable[str]) -> str:
    parts: list[str] = []
    for key in keys:
        value = attrs.get(key)
        if value is None:
            continue
        if isinstance(value, str) and len(value) > HASH_PREVIEW_LEN:
            prefix = HASH_PREVIEW_LEN // 2
            value = f"{value[:prefix]}…"
        parts.append(f"{key}={value}")
    return ", ".join(parts)


def _build_operation_chain(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stacks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    completed: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("type")
        name = event.get("name")
        if event_type == "operation.start" and name:
            stacks[name].append(event)
        elif event_type == "operation.end" and name:
            start = stacks[name].pop() if stacks.get(name) else None
            completed.append({"name": name, "start": start, "end": event})
    completed.sort(key=lambda entry: (entry["start"] or entry["end"]).get("ts", 0.0))
    return completed


def _find_event(
    events: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    for event in events:
        if predicate(event):
            return event
    return None


def _find_last_success(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("status") == "ok":
            return event
    return None


def _find_first_failure(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _find_event(events, lambda evt: evt.get("status") == "error")


def _format_event_summary(event: dict[str, Any] | None) -> str:
    if event is None:
        return "n/a"
    name = event.get("name") or event.get("type")
    attrs = event.get("attrs") or {}
    message = event.get("message")
    summary_attrs = _format_attrs(attrs, ("reason", "fallback", "status_code"))
    parts = [f"{name}"]
    if summary_attrs:
        parts.append(f"({summary_attrs})")
    if message:
        parts.append(f"- {message}")
    return " ".join(parts)


def _collect_stage_entries(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    reversed_events = list(reversed(events))
    stage_entries: list[tuple[str, dict[str, Any]]] = []
    for label, stage_type in STAGE_EVENT_MAP.items():
        stage_event = next((evt for evt in reversed_events if evt.get("type") == stage_type), None)
        if stage_event is not None:
            stage_entries.append((label, stage_event))
    return stage_entries


def _collect_skip_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evt for evt in events if (evt.get("type") or "").endswith(".skip")]


def _collect_decisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evt for evt in events if evt.get("type") == "decision"]


def _render_header(
    session: str,
    run_id: str | None,
    last_success: dict[str, Any] | None,
    first_failure: dict[str, Any] | None,
) -> list[str]:
    return [
        f"- **Session:** `{session}`",
        f"- **Run:** `{run_id}`" if run_id else "- **Run:** `n/a`",
        f"- **Last Success:** {_format_event_summary(last_success)}",
        f"- **First Failure:** {_format_event_summary(first_failure)}",
        "",
    ]


def _render_operations_section(operations: list[dict[str, Any]]) -> list[str]:
    lines = ["## Operation Chain"]
    if not operations:
        lines.append("No operations recorded for this run.")
        return lines
    for idx, entry in enumerate(operations, 1):
        end = entry["end"]
        status = end.get("status", "ok")
        glyph = GLYPHS.get(status, "•")
        duration = end.get("attrs", {}).get("duration_ms")
        duration_text = f"{duration} ms" if duration is not None else "n/a"
        start_attrs = entry["start"].get("attrs") if entry["start"] else {}
        summary_attrs = _format_attrs(
            start_attrs,
            ("limit", "query_chars", "capability_stamp"),
        )
        detail = f" ({summary_attrs})" if summary_attrs else ""
        lines.append(f"{idx}. {glyph} **{entry['name']}** — {duration_text}{detail}")
    return lines


def _render_stage_section(stages: list[tuple[str, dict[str, Any]]]) -> list[str]:
    lines = ["## Stage Durations"]
    if not stages:
        lines.append("No stage telemetry recorded.")
        return lines
    for label, event in stages:
        attrs = event.get("attrs") or {}
        duration = attrs.get("duration_ms")
        duration_text = f"{duration} ms" if duration is not None else "n/a"
        detail = _format_attrs(
            attrs,
            (
                "mode",
                "n_texts",
                "k",
                "nprobe",
                "use_gpu",
                "channels",
                "total",
                "returned",
                "asked_for",
            ),
        )
        suffix = f" ({detail})" if detail else ""
        lines.append(f"- **{label}**: {duration_text}{suffix}")
    return lines


def _render_skip_section(skips: list[dict[str, Any]]) -> list[str]:
    lines = ["## Channel Skips"]
    if not skips:
        lines.append("No channel skips.")
        return lines
    for evt in skips:
        attrs = evt.get("attrs") or {}
        reason = attrs.get("reason", "unspecified")
        message = attrs.get("message")
        suffix = f" ({message})" if message else ""
        lines.append(f"- `{evt.get('name')}` — {reason}{suffix}")
    return lines


def _render_decisions_section(decisions: list[dict[str, Any]]) -> list[str]:
    lines = ["## Decisions"]
    if not decisions:
        lines.append("No decision events recorded.")
        return lines
    for evt in decisions:
        attrs = evt.get("attrs") or {}
        summary = _format_attrs(attrs, ("enabled", "reason", "fallback"))
        status = evt.get("status", "ok")
        glyph = GLYPHS.get(status, "•")
        detail = f" ({summary})" if summary else ""
        lines.append(f"- {glyph} `{evt.get('name')}`{detail}")
    return lines


def _render_report(session: str, run_id: str | None, events: list[dict[str, Any]]) -> str:
    """Render a Markdown report for the provided session.

    Extended Summary
    ----------------
    This function generates a human-readable Markdown report from timeline events
    for a specific session. It analyzes events to extract operation chains, stage
    entries, skip events, and decisions, then formats them into structured sections.
    Used by the diagnostics CLI to produce readable reports for debugging and
    performance analysis.

    Parameters
    ----------
    session : str
        Session identifier to filter events and include in report header.
    run_id : str | None, optional
        Optional run identifier to include in report header. If None, omitted.
    events : list[dict[str, Any]]
        Timeline events for the session, typically loaded from JSONL files.
        Events are analyzed to extract operations, stages, skips, and decisions.

    Returns
    -------
    str
        Markdown payload describing the session timeline with sections:
        - Header (session, run_id, success/failure status)
        - Operations chain
        - Stage entries
        - Skip events
        - Decisions

    Notes
    -----
    This function processes events to build a structured report. It identifies
    the last successful operation and first failure to provide quick status
    overview. Time complexity: O(n) where n is the number of events.
    """
    last_success = _find_last_success(events)
    first_failure = _find_first_failure(events)
    operations = _build_operation_chain(events)
    skips = _collect_skip_events(events)
    decisions = _collect_decisions(events)
    stages = _collect_stage_entries(events)

    lines: list[str] = ["# Session Report", ""]
    lines.extend(_render_header(session, run_id, last_success, first_failure))
    lines.extend(_render_operations_section(operations))
    lines.append("")
    lines.extend(_render_stage_section(stages))
    lines.append("")
    lines.extend(_render_skip_section(skips))
    lines.append("")
    lines.extend(_render_decisions_section(decisions))
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for the diagnostics CLI.

    Extended Summary
    ----------------
    This CLI entry point renders timeline events from JSONL files as Markdown
    reports. It filters events by session identifier, generates a structured
    report, and writes it to the specified output file. Used for post-processing
    timeline data to produce human-readable diagnostics reports.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. If None, uses `sys.argv[1:]`. Arguments are:
        --events (path to events JSONL file), --session (session identifier),
        --out (output Markdown file path).

    Returns
    -------
    int
        Zero on success, non-zero when no events were processed or file I/O fails.

    Notes
    -----
    This tool reads timeline events from JSONL files and generates Markdown
    reports. It filters events by session and processes them to extract
    operations, stages, skips, and decisions. Time complexity: O(n) where n
    is the number of events in the input file.
    """
    parser = argparse.ArgumentParser(description="Render timeline JSONL as Markdown.")
    parser.add_argument("--events", required=True, help="Path to events-*.jsonl file")
    parser.add_argument("--session", required=True, help="Session identifier to filter")
    parser.add_argument("--out", required=True, help="Markdown destination")
    args = parser.parse_args(argv)

    all_events = _load_events(Path(args.events), args.session)
    run_id, events = _select_run_events(all_events)
    if not events:
        Path(args.out).write_text(
            f"# Session Report\n\nNo events found for session `{args.session}`.\n",
            encoding="utf-8",
        )
        return 0

    report = _render_report(args.session, run_id, events)
    Path(args.out).write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
