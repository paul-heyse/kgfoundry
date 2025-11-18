"""Analytics command."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.cli.enrich import app
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.services.enrich.analytics import basic_stats
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.scan import scan_repo

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")
PRETTY_OPTION = typer.Option(
    default=True,
    help="Pretty-print JSON output",
    show_default=True,
)


@app.command("analytics")
def analytics(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    pretty: bool = PRETTY_OPTION,
) -> None:
    """Compute and print summary analytics for a scan."""
    paths = resolve_application_paths({"BASE_DIR": repo_root, "DATA_DIR": out_dir})
    raise_on_errors(validate_paths(paths))
    ctx = PipelineContext.from_paths(paths)
    stats = basic_stats(ctx, scan_repo(ctx))
    typer.echo(json.dumps(stats, indent=2 if pretty else None))
