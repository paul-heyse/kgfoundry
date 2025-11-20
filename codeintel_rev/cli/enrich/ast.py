# SPDX-License-Identifier: MIT
"""CLI command for emitting AST node/metric artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich._graph_utils import DEFAULT_EXCLUDES, resolve_paths
from codeintel_rev.services.enrich.context import DEFAULT_MAX_FILE_BYTES
from codeintel_rev.services.enrich.graph_steps import FileDiscoverySettings, build_ast_artifacts

REPO_ROOT_OPTION = typer.Option(Path(), "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option(
    Path("build/enrich"),
    "--out-dir",
    help="Output directory for enrichment artifacts.",
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

@app.command("ast")
def build_ast(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    include: list[str] | None = INCLUDE_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
) -> None:
    """Emit AST nodes/metrics Parquet + JSONL pairs for a repository."""
    include_globs = tuple(include or ())
    paths, ctx = resolve_paths(repo_root, out_dir)
    filters = FileDiscoverySettings(
        include=include_globs,
        exclude=DEFAULT_EXCLUDES,
        max_file_bytes=max_file_bytes,
    )
    result = build_ast_artifacts(
        ctx,
        out_dir=paths.data_dir,
        filters=filters,
    )
    typer.echo(f"AST nodes written: {result.nodes_path}")
    typer.echo(f"AST metrics written: {result.metrics_path}")
    typer.echo(f"AST parquet directory: {result.parquet_dir}")
