"""Diagnostics CLI for rendering run reports from session event ledgers."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from codeintel_rev.observability.run_report import LedgerRunReport, infer_stop_reason, load_ledger

__all__ = ["app", "main"]

app = typer.Typer(no_args_is_help=True, add_completion=False)


class ReportFormat(StrEnum):
    """Supported output encodings for diagnostics reports."""

    MARKDOWN = "markdown"
    JSON = "json"


EventRecord = dict[str, Any]


def _coerce_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _coerce_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _event_ts(event: Mapping[str, object]) -> int:
    raw = event.get("ts")
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def _event_attrs(event: Mapping[str, object]) -> Mapping[str, object]:
    attrs = event.get("attrs")
    if isinstance(attrs, Mapping):
        return attrs
    return {}


def _stage_label(event_type: str) -> str:
    return event_type.rsplit(".", 1)[0] if "." in event_type else event_type


def _group_events_by_run(
    events: Sequence[EventRecord],
    session_id: str,
) -> dict[str, list[EventRecord]]:
    grouped: dict[str, list[EventRecord]] = {}
    for event in events:
        if _coerce_str(event.get("session_id")) != session_id:
            continue
        run_id = _coerce_str(event.get("run_id"))
        if run_id is None:
            continue
        grouped.setdefault(run_id, []).append(event)
    return grouped


def _max_ts(events: Sequence[EventRecord]) -> tuple[int, int]:
    best_ts = -1
    index = -1
    for idx, event in enumerate(events):
        ts = _event_ts(event)
        if ts > best_ts or (ts == best_ts and idx > index):
            best_ts = ts
            index = idx
    return best_ts, index


def _select_run(
    grouped: Mapping[str, Sequence[EventRecord]],
    requested_run: str | None,
) -> tuple[str, Sequence[EventRecord]]:
    if requested_run is not None:
        if requested_run not in grouped:
            message = f"Run '{requested_run}' not found for the provided session."
            raise typer.BadParameter(message)
        return requested_run, grouped[requested_run]
    if not grouped:
        message = "No runs found for the provided session."
        raise typer.BadParameter(message)
    run_id, events = max(grouped.items(), key=lambda item: _max_ts(item[1]))
    return run_id, events


def _stage_rows(events: Sequence[EventRecord]) -> list[tuple[str, str, float, str]]:
    rows: list[tuple[str, str, float, str]] = []
    for event in events:
        event_type = _coerce_str(event.get("type"))
        if not event_type or not event_type.endswith(".end"):
            continue
        duration = _coerce_number(_event_attrs(event).get("duration_ms"))
        if duration is None:
            continue
        stage = _stage_label(event_type)
        component = _coerce_str(event.get("name")) or stage
        status = _coerce_str(event.get("status")) or "unknown"
        rows.append((stage, component, duration, status))
    return rows


def _skip_rows(events: Sequence[EventRecord]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for event in events:
        event_type = _coerce_str(event.get("type"))
        if not event_type or not event_type.endswith(".skip"):
            continue
        attrs = _event_attrs(event)
        reason = _coerce_str(attrs.get("reason"))
        if not reason:
            continue
        stage = _stage_label(event_type)
        component = _coerce_str(event.get("name")) or stage
        rows.append((stage, component, reason))
    return rows


def _render_stage_section(events: Sequence[EventRecord]) -> list[str]:
    lines = ["## Stage Durations", ""]
    rows = _stage_rows(events)
    if not rows:
        lines.append("_No completed stages recorded._")
        lines.append("")
        return lines
    lines.append("| Stage | Component | Duration (ms) | Status |")
    lines.append("| --- | --- | ---: | --- |")
    for stage, component, duration, status in rows:
        lines.append(f"| {stage} | {component} | {duration:.0f} | {status} |")
    lines.append("")
    return lines


def _render_skip_section(events: Sequence[EventRecord]) -> list[str]:
    lines = ["## Channel Skips", ""]
    rows = _skip_rows(events)
    if not rows:
        lines.append("_No channel skips recorded._")
        lines.append("")
        return lines
    lines.append("| Channel | Component | Reason |")
    lines.append("| --- | --- | --- |")
    for stage, component, reason in rows:
        lines.append(f"| {stage} | {component} | {reason} |")
    lines.append("")
    return lines


def _render_markdown(session_id: str, run_id: str, events: Sequence[EventRecord]) -> str:
    lines = [
        "# Diagnostics Run Report",
        "",
        f"**Session:** `{session_id}`",
        f"**Run:** `{run_id}`",
        "",
    ]
    lines.extend(_render_stage_section(events))
    lines.extend(_render_skip_section(events))
    rendered = "\n".join(lines).rstrip()
    return f"{rendered}\n"


def _structured_report(
    run_id: str, ledger_path: Path, events: Sequence[EventRecord]
) -> LedgerRunReport:
    steps = [dict(event) for event in events]
    warnings = [
        str(step.get("detail"))
        for step in steps
        if step.get("status") == "degraded" and step.get("detail")
    ]
    return LedgerRunReport(
        run_id=run_id,
        stopped_because=infer_stop_reason(steps),
        steps=steps,
        warnings=warnings,
        ledger_path=str(ledger_path),
    )


@app.command("session")
def session_report(  # pragma: no cover - exercised via pytests
    events: Annotated[
        Path,
        typer.Option(
            ...,
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Events JSONL ledger.",
        ),
    ],
    session: Annotated[str, typer.Option(..., help="Session identifier to summarise.")],
    run: Annotated[
        str | None, typer.Option(None, help="Optional run identifier to render.")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            None, help="Optional output path. When omitted the report is printed to stdout."
        ),
    ] = None,
    fmt: Annotated[
        ReportFormat,
        typer.Option(
            ReportFormat.MARKDOWN,
            "--format",
            "-f",
            case_sensitive=False,
            help="Choose markdown (default) or json output.",
        ),
    ] = ReportFormat.MARKDOWN,
) -> None:
    """Render the latest (or requested) run for a session from an events ledger.

    Parameters
    ----------
    events : Path
        JSONL ledger containing mixed run events. Must exist and be readable.
        Provided via typer.Option.
    session : str
        Session identifier to filter runs. Provided via typer.Option.
    run : str | None
        Optional run identifier to force selection. Defaults to None.
        Provided via typer.Option.
    out : Path | None
        Optional output path. When omitted the report is printed to stdout.
        Defaults to None. Provided via typer.Option.
    fmt : ReportFormat
        Output format for the report (markdown or json). Defaults to MARKDOWN.
        Provided via typer.Option with flag "--format".

    Raises
    ------
    typer.BadParameter
        If the session identifier is empty, the requested run is missing, or no
        events exist for the resolved run.
    """
    session_id = session.strip()
    if not session_id:
        message = "Session identifier cannot be blank."
        raise typer.BadParameter(message)
    ledger_events = load_ledger(events)
    grouped = _group_events_by_run(ledger_events, session_id)
    selected_run, run_events = _select_run(grouped, run)
    if not run_events:
        message = "No events recorded for the selected run."
        raise typer.BadParameter(message)

    if fmt is ReportFormat.JSON:
        payload = json.dumps(asdict(_structured_report(selected_run, events, run_events)), indent=2)
    else:
        payload = _render_markdown(session_id, selected_run, run_events)

    if out is None:
        typer.echo(payload.rstrip("\n"))
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    text = payload if payload.endswith("\n") else f"{payload}\n"
    out.write_text(text, encoding="utf-8")


@app.command("run")
def ledger_report(
    run_id: Annotated[str, typer.Argument(..., help="Run identifier returned via X-Run-Id")],
    data_dir: Annotated[
        Path,
        typer.Option(
            Path("data"),
            "--data-dir",
            "-d",
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Telemetry data directory (default: ./data).",
        ),
    ] = Path("data"),
) -> None:
    """Render structured JSON for a run ledger stored under ``data/telemetry``.

    Parameters
    ----------
    run_id : str
        Run identifier returned via API response headers. Provided via typer.Argument.
    data_dir : Path
        Data directory whose telemetry sub-directory stores run ledgers.
        Defaults to Path("data"). Provided via typer.Option.

    Raises
    ------
    typer.BadParameter
        If the run ledger cannot be located under ``data/telemetry``.
    """
    ledger_path = data_dir.resolve() / "telemetry" / "runs"
    matches = sorted(ledger_path.glob(f"*/{run_id}.jsonl"), reverse=True)
    if not matches:
        message = f"Run ledger {run_id} not found under {ledger_path}"
        raise typer.BadParameter(message)
    report = _structured_report(run_id, matches[0], load_ledger(matches[0]))
    typer.echo(json.dumps(asdict(report), indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    """
    Invoke the Typer application while supporting programmatic argv injection.

    Parameters
    ----------
    argv : Sequence[str] | None
        Argument vector override. When None, ``sys.argv[1:]`` is used.

    Returns
    -------
    int
        Process-style exit code emitted by Typer.
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    command = typer.main.get_command(app)
    known_commands = set(getattr(command, "commands", {}).keys())
    forwarded_args = args
    if args and args[0] not in known_commands:
        forwarded_args = ["session", *args]
    try:
        command.main(
            args=forwarded_args,
            prog_name="codeintel-diagnostics",
            standalone_mode=False,
        )
    except SystemExit as exc:  # pragma: no cover - Typer handles user exits
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
