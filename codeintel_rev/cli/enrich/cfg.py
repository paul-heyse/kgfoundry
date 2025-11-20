# SPDX-License-Identifier: MIT
"""CLI commands for building CFG/DFG scaffolding."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import resolve_paths
from codeintel_rev.services.enrich.graph_steps import build_cfg_artifacts

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
    help="Ingest CFG/DFG data into DuckDB.",
    show_default=True,
)


@app.command("cfg")
def build_cfg(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
) -> None:
    """Build control-flow graphs for Python functions."""
    paths, ctx = resolve_paths(repo_root, out_dir)
    result = build_cfg_artifacts(ctx, out_dir=paths.data_dir, ingest_cfg=ingest, ingest_dfg=False)
    typer.echo(f"CFG blocks written: {result.blocks_path}")
    typer.echo(f"CFG edges written: {result.edges_path}")
    if ingest:
        typer.echo("CFG data ingested into DuckDB.")


@app.command("dfg")
def build_dfg(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
) -> None:
    """Build data-flow graphs for Python functions."""
    paths, ctx = resolve_paths(repo_root, out_dir)
    result = build_cfg_artifacts(ctx, out_dir=paths.data_dir, ingest_cfg=False, ingest_dfg=ingest)
    typer.echo(f"DFG edges written: {result.dfg_path}")
    if ingest:
        typer.echo("DFG data ingested into DuckDB.")
