"""Telemetry-focused CLI commands."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.observability.reporting import (
    build_timeline_run_report,
    render_timeline_markdown,
    timeline_mermaid,
)
from codeintel_rev.observability.runpack import make_runpack

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


class OutputFormat(Enum):
    """Output formats supported by the run report command."""

    JSON = "json"
    MARKDOWN = "md"
    MERMAID = "mmd"


@app.command("report")
def run_report(
    session_id: SessionArg,
    run_id: RunIdOption = None,
    timeline_dir: TimelineDirOption = None,
    fmt: Annotated[
        OutputFormat,
        typer.Option(
            OutputFormat.JSON,
            "--format",
            "-f",
            case_sensitive=False,
            help="Select json (default), md, or mmd output.",
        ),
    ] = OutputFormat.JSON,
) -> None:
    """Render a run report from Timeline JSONL artifacts."""
    report = build_timeline_run_report(
        session_id=session_id,
        run_id=run_id,
        timeline_dir=timeline_dir,
    )
    if fmt is OutputFormat.JSON:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    elif fmt is OutputFormat.MARKDOWN:
        typer.echo(render_timeline_markdown(report))
    else:
        typer.echo(timeline_mermaid(report))


@app.command("runpack")
def runpack(
    session_id: SessionArg,
    run_id: RunIdOption = None,
    reason: Annotated[
        str | None,
        typer.Option(
            None,
            "--reason",
            help="Optional reason stored in metadata.",
        ),
    ] = None,
    trace_id: Annotated[
        str | None,
        typer.Option(
            None,
            "--trace-id",
            help="Optional trace identifier to record.",
        ),
    ] = None,
) -> None:
    """Create a runpack zip for the specified session/run.

    This command packages telemetry artifacts (timeline events, run reports, and
    configuration snapshots) into a zip archive for offline analysis. The runpack
    includes all events for the specified session and optional run identifier,
    making it useful for debugging and performance analysis.

    Parameters
    ----------
    session_id : str
        Session identifier to inspect. Provided via typer.Argument.
    run_id : str | None
        Optional run identifier when multiple runs share a session. Defaults to None.
        Provided via typer.Option with flag "--run-id".
    reason : str | None
        Optional reason stored in metadata. Defaults to None. Provided via
        typer.Option with flag "--reason".
    trace_id : str | None
        Optional trace identifier to record. Defaults to None. Provided via
        typer.Option with flag "--trace-id".

    Raises
    ------
    typer.BadParameter
        Raised when the application context cannot be initialized.
    """
    try:
        context = ApplicationContext.create()
    except Exception as exc:  # pragma: no cover - configuration errors
        message = f"Failed to initialize application context: {exc}"
        raise typer.BadParameter(message) from exc
    artifact = make_runpack(
        context=context,
        session_id=session_id,
        run_id=run_id,
        trace_id=trace_id,
        reason=reason,
    )
    typer.echo(str(artifact))
