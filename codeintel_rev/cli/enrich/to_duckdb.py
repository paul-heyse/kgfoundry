# SPDX-License-Identifier: MIT
"""DuckDB ingestion command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.services.enrich import to_duckdb as duckdb_service


@app.command("to-duckdb")
def to_duckdb(
    modules_jsonl: Annotated[
        Path,
        typer.Option(
            "--modules-jsonl",
            help="Path to modules.jsonl produced by the enrichment CLI.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    db_path: Annotated[
        Path,
        typer.Option(
            "--db-path",
            "--db",
            help="Target DuckDB database file.",
            dir_okay=False,
            writable=True,
        ),
    ] = Path("build/enrich/enrich.duckdb"),
) -> None:
    """Load ``modules.jsonl`` into DuckDB (idempotent on ``path``)."""
    count = duckdb_service.load_modules_jsonl(modules_jsonl, db_path)
    typer.echo(f"[to-duckdb] Loaded {count} rows into {db_path}")
