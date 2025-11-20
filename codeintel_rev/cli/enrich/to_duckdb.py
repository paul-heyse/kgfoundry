"""Write scan results to DuckDB."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.cli.enrich import app
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext, PipelineInitOptions
from codeintel_rev.services.enrich.scan import scan_repo
from codeintel_rev.services.enrich.to_duckdb import write_to_duckdb

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")
DUCKDB_PATH_OPTION = typer.Option(None, "--duckdb-path", help="DuckDB file to write")
TABLE_OPTION = typer.Option("modules", "--table", help="Table name")
REPLACE_OPTION = typer.Option(
    default=True,
    help="Replace the target table if it exists",
    show_default=True,
)


@app.command("to-duckdb")
def to_duckdb(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    duckdb_path: Path | None = DUCKDB_PATH_OPTION,
    table: str = TABLE_OPTION,
    replace: bool = REPLACE_OPTION,
) -> None:
    """Scan the repo and persist records inside DuckDB."""
    paths = resolve_application_paths({"BASE_DIR": repo_root, "DATA_DIR": out_dir})
    raise_on_errors(validate_paths(paths))
    target = duckdb_path or (paths.data_dir / "enrich.duckdb")
    options = PipelineInitOptions(enable_db=True, duckdb_path=str(target))
    ctx = PipelineContext.from_paths(paths, options=options)
    records = scan_repo(ctx)
    write_to_duckdb(ctx, records, table=table, replace=replace)
    typer.echo(f"Wrote {len(records)} rows to {target}::{table}")
