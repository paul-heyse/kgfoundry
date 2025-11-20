# SPDX-License-Identifier: MIT
"""CLI command for building call graph artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import DEFAULT_EXCLUDES, resolve_paths
from codeintel_rev.services.enrich.context import DEFAULT_MAX_FILE_BYTES
from codeintel_rev.services.enrich.graph_steps import (
    FileDiscoverySettings,
    build_callgraph_artifacts,
)

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
INCLUDE_OPTION = typer.Option(
    None,
    "--include",
    help="Include glob(s); repeat to supply multiple patterns.",
    show_default=False,
)
MAX_FILE_BYTES_OPTION = typer.Option(
    DEFAULT_MAX_FILE_BYTES,
    "--max-file-bytes",
    help="Skip files larger than this many bytes.",
)

@app.command("callgraph")
def build_callgraph_cli(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
    include: list[str] | None = INCLUDE_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
) -> None:
    """Build call graph nodes and edges for Python sources."""
    include_globs = tuple(include or ())
    paths, ctx = resolve_paths(repo_root, out_dir)
    filters = FileDiscoverySettings(
        include=include_globs,
        exclude=DEFAULT_EXCLUDES,
        max_file_bytes=max_file_bytes,
    )
    result = build_callgraph_artifacts(
        ctx,
        out_dir=paths.data_dir,
        ingest=ingest,
        filters=filters,
    )
    typer.echo(f"Call graph nodes written: {result.nodes_path}")
    typer.echo(f"Call graph edges written: {result.edges_path}")
    if ingest:
        typer.echo("Call graph ingested into DuckDB.")
