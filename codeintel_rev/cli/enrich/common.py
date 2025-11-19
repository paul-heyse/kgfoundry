# SPDX-License-Identifier: MIT
"""Shared helpers for the enrich Typer application."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

import typer

from codeintel_rev.enrich.errors import StageError
from codeintel_rev.services.enrich.context import (
    AnalyticsOptions,
    CLIContextState,
    PipelineOptions,
    PipelineResult,
)
from codeintel_rev.services.enrich.scan import run_pipeline

LOGGER = logging.getLogger(__name__)


def attach_argv_normalizer(
    app: typer.Typer, normalizer: Callable[[Sequence[str]], list[str]]
) -> None:
    """Attach argv normalizer metadata for CLI tests."""
    typed_app = cast("Any", app)
    typed_app.argv_normalizer = normalizer


ROOT_OPTION = typer.Option(
    Path().resolve(),
    "--root",
    help="Repo or subfolder to scan.",
    exists=True,
    file_okay=False,
    dir_okay=True,
    readable=True,
)
SCIP_OPTION = typer.Option(
    None,
    "--scip",
    help="Path to SCIP index.json",
    exists=True,
    dir_okay=False,
    readable=True,
)
OUT_OPTION = typer.Option(
    Path("codeintel_rev/io/ENRICHED"),
    "--out",
    help="Output directory for enrichment artifacts.",
    dir_okay=True,
)
PYREFLY_OPTION = typer.Option(
    None,
    "--pyrefly-json",
    help="Optional path to a Pyrefly JSON/JSONL report.",
    exists=True,
    dir_okay=False,
    readable=True,
)
TAGS_OPTION = typer.Option(
    None,
    "--tags-yaml",
    help="Optional tagging rules YAML.",
    exists=True,
    dir_okay=False,
    readable=True,
)
COVERAGE_OPTION = typer.Option(
    Path("coverage.xml"),
    "--coverage-xml",
    help="Optional path to coverage XML (Cobertura format).",
    dir_okay=False,
)
ONLY_OPTION = typer.Option(
    None,
    "--only",
    help="Glob patterns (repeatable) limiting modules relative to --root.",
)
MAX_FILE_BYTES_OPTION = typer.Option(
    2_000_000,
    "--max-file-bytes",
    help="Skip files larger than this many bytes (default: 2MB).",
)
_DEFAULT_ENABLE_OWNERS = True
_DEFAULT_EMIT_SLICES = False
_DEFAULT_EMIT_AST = True
_DEFAULT_DRY_RUN = False

OWNERS_OPTION = typer.Option(
    _DEFAULT_ENABLE_OWNERS,
    "--owners/--no-owners",
    help="Compute ownership information prior to exports.",
)
HISTORY_WINDOW_OPTION = typer.Option(
    90,
    "--history-window-days",
    help="History window for ownership computations.",
)
COMMITS_WINDOW_OPTION = typer.Option(
    50,
    "--commits-window",
    help="Number of commits inspected for ownership.",
)
EMIT_SLICES_OPTION = typer.Option(
    _DEFAULT_EMIT_SLICES,
    "--emit-slices/--no-emit-slices",
    help="Emit Markdown slices for tag groups.",
)
SLICES_FILTER_OPTION = typer.Option(
    None,
    "--slices-filter",
    help="Optional tag filters for slices.",
)
OVERLAYS_CONFIG_OPTION = typer.Option(
    None,
    "--config",
    help="Overlay config JSON/YAML.",
)
OVERLAYS_SET_OPTION = typer.Option(
    None,
    "--set",
    help="Override overlay option (repeatable KEY=VALUE).",
)
EMIT_AST_OPTION = typer.Option(
    _DEFAULT_EMIT_AST,
    "--emit-ast/--no-emit-ast",
    help="Emit AST nodes/metrics alongside exports.",
)
DRY_RUN_OPTION = typer.Option(
    _DEFAULT_DRY_RUN,
    "--dry-run/--no-dry-run",
    help="Run computations and log counts without writing artifacts.",
)

GLOBAL_OPTIONS_HELP = """Repo enrichment utilities (scan + overlays)."""

_GLOBAL_VALUE_FLAGS = {
    "--root",
    "--scip",
    "--out",
    "--pyrefly-json",
    "--tags-yaml",
    "--coverage-xml",
    "--only",
    "--max-file-bytes",
    "--history-window-days",
    "--commits-window",
    "--slices-filter",
}
_GLOBAL_BOOL_FLAGS = {
    "--owners",
    "--no-owners",
    "--emit-slices",
    "--no-emit-slices",
}
_GLOBAL_MIN_ARG_COUNT = 3


def normalize_global_cli_args(argv: Sequence[str]) -> list[str]:
    """Return arguments with known global options positioned before the command.

    Parameters
    ----------
    argv : Sequence[str]
        Raw argv forwarded by Typer.

    Returns
    -------
    list[str]
        Normalised argv with global flags moved ahead of the command name.
    """
    if len(argv) < _GLOBAL_MIN_ARG_COUNT:
        return list(argv)
    script, *rest = argv
    globals_segment: list[str] = []
    remaining: list[str] = []
    idx = 0
    while idx < len(rest):
        token = rest[idx]
        flag, eq, _inline = token.partition("=")
        if flag in _GLOBAL_VALUE_FLAGS:
            if eq:
                globals_segment.append(token)
                idx += 1
                continue
            if idx + 1 < len(rest):
                globals_segment.extend([flag, rest[idx + 1]])
                idx += 2
                continue
            remaining.append(token)
            idx += 1
            continue
        if flag in _GLOBAL_BOOL_FLAGS:
            globals_segment.append(token)
            idx += 1
            continue
        remaining.append(token)
        idx += 1
    return [script, *globals_segment, *remaining]


def shared_options(  # noqa: PLR0913, PLR0917
    # pragma: no cover - Typer wiring
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
) -> None:
    """Capture global enrichment options shared by all subcommands."""
    pipeline_options = PipelineOptions(
        root=root.resolve(),
        scip=scip.resolve() if scip else None,
        out=out.resolve(),
        pyrefly_json=pyrefly_json.resolve() if pyrefly_json else None,
        tags_yaml=tags_yaml.resolve() if tags_yaml else None,
        coverage_xml=coverage_xml.resolve(),
        only=tuple(only or ()),
        max_file_bytes=max_file_bytes,
    )
    analytics_options = AnalyticsOptions(
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=tuple(slices_filter or ()),
    )
    ctx.obj = CLIContextState(pipeline=pipeline_options, analytics=analytics_options)


def ensure_state(ctx: typer.Context) -> CLIContextState:
    """Return CLI context state, creating a default if necessary.

    Parameters
    ----------
    ctx : typer.Context
        Typer context carrying the shared object slot.

    Returns
    -------
    CLIContextState
        Existing or newly created state bundle.
    """
    state = ctx.obj
    if not isinstance(state, CLIContextState):
        state = CLIContextState()
        ctx.obj = state
    return state


def execute_pipeline(state: CLIContextState) -> PipelineResult:
    """Execute the enrichment pipeline for the current state.

    Parameters
    ----------
    state : CLIContextState
        Shared CLI state carrying pipeline options.

    Returns
    -------
    PipelineResult
        Aggregate pipeline result bundle.
    """
    return run_pipeline(pipeline=state.pipeline)


def handle_stage_error(exc: StageError) -> NoReturn:
    """Render a StageError and exit the CLI with code 1.

    Parameters
    ----------
    exc : StageError
        Exception raised by the pipeline orchestration.

    Raises
    ------
    typer.Exit
        Always raised with exit code ``1`` after logging diagnostics.
    """
    LOGGER.error("stage_error %s", exc.log_extra(), exc_info=exc)
    message = exc.detail or exc.reason
    typer.echo(f"[{exc.stage}] {message}", err=True)
    raise typer.Exit(1) from exc


def handle_dry_run(
    command: str,
    *,
    dry_run: bool,
    result: PipelineResult,
) -> bool:
    """Emit deterministic dry-run summaries.

    Parameters
    ----------
    command : str
        Command name to display in the dry-run summary.
    dry_run : bool
        Whether dry-run mode is enabled.
    result : PipelineResult
        Pipeline execution result containing module rows, edges, and tags.

    Returns
    -------
    bool
        ``True`` when the caller should exit early (dry-run enabled).
    """
    if not dry_run:
        return False
    typer.echo(
        f"[{command}] DRY RUN: modules={len(result.module_rows)} "
        f"edges={len(result.symbol_edges)} tags={len(result.tag_index)}"
    )
    return True


__all__ = [
    "COMMITS_WINDOW_OPTION",
    "COVERAGE_OPTION",
    "DRY_RUN_OPTION",
    "EMIT_AST_OPTION",
    "EMIT_SLICES_OPTION",
    "GLOBAL_OPTIONS_HELP",
    "OUT_OPTION",
    "OVERLAYS_CONFIG_OPTION",
    "OVERLAYS_SET_OPTION",
    "OWNERS_OPTION",
    "PYREFLY_OPTION",
    "ROOT_OPTION",
    "SCIP_OPTION",
    "SLICES_FILTER_OPTION",
    "TAGS_OPTION",
    "attach_argv_normalizer",
    "ensure_state",
    "execute_pipeline",
    "handle_dry_run",
    "handle_stage_error",
    "normalize_global_cli_args",
    "shared_options",
]
