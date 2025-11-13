"""Telemetry-focused CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.observability.reporting import build_timeline_run_report

app = typer.Typer(help="Telemetry diagnostics utilities.", no_args_is_help=True)

SessionArg = Annotated[str, typer.Argument(..., help="Session identifier to inspect.")]
RunIdOption = Annotated[
    str | None,
    typer.Option(
        None,
        "--run-id",
        help="Optional run identifier when multiple runs share a session.",
    ),
]
TimelineDirOption = Annotated[
    Path | None,
    typer.Option(
        None,
        "--timeline-dir",
        help="Directory containing Timeline JSONL files (defaults to CODEINTEL_DIAG_DIR).",
    ),
]


@app.command("report")
def run_report(
    session_id: SessionArg,
    run_id: RunIdOption = None,
    timeline_dir: TimelineDirOption = None,
) -> None:
    """Render a run report from Timeline JSONL artifacts."""
    report = build_timeline_run_report(
        session_id=session_id,
        run_id=run_id,
        timeline_dir=timeline_dir,
    )
    typer.echo(json.dumps(report.to_dict(), indent=2))
