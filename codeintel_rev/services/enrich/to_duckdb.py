# SPDX-License-Identifier: MIT
"""DuckDB ingestion helpers for enrichment."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.models import ModuleRecord as SimpleModuleRecord


def load_modules_jsonl(modules_jsonl: Path, db_path: Path) -> int:
    """Load ``modules.jsonl`` rows into DuckDB.

    Parameters
    ----------
    modules_jsonl : Path
        Path to the JSONL file containing module records to ingest.
    db_path : Path
        Path to the DuckDB database file where records will be loaded.

    Returns
    -------
    int
        Number of ingested rows.
    """
    return ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)


def _quote_identifier(name: str) -> str:
    """Return a DuckDB-safe quoted identifier.

    Parameters
    ----------
    name : str
        Unquoted identifier name to quote.

    Returns
    -------
    str
        Quoted identifier string safe for use in DuckDB SQL queries.
        Double quotes within the name are escaped as two double quotes.
    """
    return f'"{name.replace('"', '""')}"'


def write_to_duckdb(
    ctx: PipelineContext,
    records: list[SimpleModuleRecord],
    *,
    table: str = "modules",
    replace: bool = True,
) -> None:
    """Write service module records into DuckDB using the context connection.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing DuckDB connection. Must have been created
        with ``enable_db=True``.
    records : list[SimpleModuleRecord]
        List of module records to write to the database.
    table : str, optional
        Table name to write records to. Defaults to "modules".
    replace : bool, optional
        Whether to drop and recreate the table if it exists. Defaults to True.

    Raises
    ------
    RuntimeError
        Raised when the context was not created with ``enable_db=True``.
    """
    if ctx.db is None:
        message = "DuckDB connection is not enabled for this context."
        raise RuntimeError(message)
    cur = ctx.db.cursor()
    quoted_table = _quote_identifier(table)
    if replace:
        cur.execute(f"DROP TABLE IF EXISTS {quoted_table}")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quoted_table} (
            path TEXT,
            module TEXT,
            language TEXT,
            loc INTEGER,
            tags JSON,
            meta JSON
        )
        """
    )
    rows = [
        (
            str(record.path),
            record.module,
            record.language,
            int(record.loc),
            json.dumps(list(record.tags)),
            json.dumps(record.meta),
        )
        for record in records
    ]
    cur.executemany(f"INSERT INTO {quoted_table} VALUES (?, ?, ?, ?, ?, ?)", rows)  # noqa: S608
    ctx.db.commit()


__all__ = ["load_modules_jsonl", "write_to_duckdb"]
