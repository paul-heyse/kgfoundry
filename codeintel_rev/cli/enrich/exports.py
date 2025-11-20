"""Exports command."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.cli.enrich import app
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext, PipelineInitOptions
from codeintel_rev.services.enrich.exports import run_all_exports
from codeintel_rev.services.enrich.scan import scan_repo

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")


def _prepare_outputs(paths: ResolvedPaths) -> None:
    """Ensure output directories exist.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved application paths containing the data directory to create.
    """
    paths.data_dir.mkdir(parents=True, exist_ok=True)


@app.command("exports")
def exports(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
) -> None:
    """Emit modules.jsonl, repo map, tag index, and markdown sheets."""
    paths = resolve_application_paths({"BASE_DIR": repo_root, "DATA_DIR": out_dir})
    raise_on_errors(validate_paths(paths))
    _prepare_outputs(paths)
    ctx = PipelineContext.from_paths(paths, options=PipelineInitOptions())
    records = scan_repo(ctx)
    result = run_all_exports(ctx, records)
    typer.echo(
        "Wrote artifacts: "
        f"{result.modules_jsonl}, {result.repo_map}, {result.tag_index}, {result.markdown_dir}"
    )
