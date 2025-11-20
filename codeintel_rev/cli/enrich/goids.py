# SPDX-License-Identifier: MIT
"""CLI entry point for building GOID artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import resolve_paths
from codeintel_rev.services.enrich.graph_steps import build_goid_artifacts

REPO_ROOT_OPTION = typer.Option(Path(), "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option(
    Path("build/enrich"),
    "--out-dir",
    help="Output directory for enrichment artifacts.",
)
INGEST_DEFAULT = False

INGEST_OPTION = typer.Option(
    INGEST_DEFAULT,
    "--ingest/--no-ingest",
    help="Ingest GOIDs into the DuckDB catalog.",
    show_default=True,
)


@app.command("goids")
def build_goids_cli(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
) -> None:
    """Build GOID registry and crosswalk artifacts for a repository."""
    paths, ctx = resolve_paths(repo_root, out_dir)
    result = build_goid_artifacts(ctx, out_dir=paths.data_dir, ingest=ingest)
    if ingest:
        typer.echo("GOID registry ingested into DuckDB.")
    typer.echo(f"GOID artifacts written: {result.goids_path}, {result.crosswalk_path}")
    if ingest:
        typer.echo("GOID registry ingested into DuckDB.")
