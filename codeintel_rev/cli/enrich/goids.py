# SPDX-License-Identifier: MIT
"""CLI entry point for building GOID artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import DEFAULT_EXCLUDES, resolve_paths
from codeintel_rev.services.enrich.artifact_writer import process_artifact_dir
from codeintel_rev.services.enrich.context import DEFAULT_MAX_FILE_BYTES
from codeintel_rev.services.enrich.graph_steps import FileDiscoverySettings, build_goid_artifacts

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

@app.command("goids")
def build_goids_cli(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    ingest: bool = INGEST_OPTION,
    include: list[str] | None = INCLUDE_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
) -> None:
    """Build GOID registry and crosswalk artifacts for a repository."""
    include_globs = tuple(include or ())
    paths, ctx = resolve_paths(repo_root, out_dir)
    filters = FileDiscoverySettings(
        include=include_globs,
        exclude=DEFAULT_EXCLUDES,
        max_file_bytes=max_file_bytes,
    )
    result = build_goid_artifacts(
        ctx,
        out_dir=paths.data_dir,
        ingest=ingest,
        filters=filters,
    )
    process_artifact_dir(paths.data_dir)
    typer.echo(f"GOID artifacts written: {result.goids_path}, {result.crosswalk_path}")
    if ingest:
        typer.echo("GOID registry ingested into DuckDB.")
