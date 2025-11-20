# SPDX-License-Identifier: MIT
"""CLI command for building call graph artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import resolve_paths
from codeintel_rev.services.enrich.graph_steps import build_callgraph_artifacts

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
    help="Ingest call graph data into DuckDB.",
    show_default=True,
)


@app.command("callgraph")
def build_callgraph_cli(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
) -> None:
    """Build call graph nodes and edges for Python sources."""
    paths, ctx = resolve_paths(repo_root, out_dir)
    result = build_callgraph_artifacts(ctx, out_dir=paths.data_dir, ingest=ingest)
    typer.echo(f"Call graph nodes written: {result.nodes_path}")
    typer.echo(f"Call graph edges written: {result.edges_path}")
    if ingest:
        typer.echo("Call graph ingested into DuckDB.")
    if ingest:
        typer.echo("Call graph ingested into DuckDB.")
