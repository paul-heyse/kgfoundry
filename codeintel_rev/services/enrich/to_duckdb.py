# SPDX-License-Identifier: MIT
"""DuckDB ingestion helpers for enrichment."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl


def load_modules_jsonl(modules_jsonl: Path, db_path: Path) -> int:
    """Load ``modules.jsonl`` rows into DuckDB.

    Returns
    -------
    int
        Number of ingested rows.
    """
    return ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)


__all__ = ["load_modules_jsonl"]
