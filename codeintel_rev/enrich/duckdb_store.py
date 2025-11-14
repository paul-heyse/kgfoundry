# SPDX-License-Identifier: MIT
"""Utilities for loading enrichment artifacts into DuckDB."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.typing import gate_import

__all__ = ["DuckConn", "ensure_schema", "ingest_modules_jsonl"]

_MODULE_COLUMNS: list[tuple[str, str]] = [
    ("path", "TEXT PRIMARY KEY"),
    ("docstring", "TEXT"),
    ("doc_summary", "TEXT"),
    ("repo_path", "TEXT"),
    ("module_name", "TEXT"),
    ("stable_id", "TEXT"),
    ("doc_has_summary", "BOOLEAN"),
    ("doc_param_parity", "BOOLEAN"),
    ("doc_examples_present", "BOOLEAN"),
    ("imports", "JSON"),
    ("defs", "JSON"),
    ("exports", "JSON"),
    ("exports_declared", "JSON"),
    ("outline_nodes", "JSON"),
    ("scip_symbols", "JSON"),
    ("parse_ok", "BOOLEAN"),
    ("errors", "JSON"),
    ("tags", "JSON"),
    ("type_errors", "INTEGER"),
    ("type_error_count", "INTEGER"),
    ("doc_metrics", "JSON"),
    ("doc_items", "JSON"),
    ("annotation_ratio", "JSON"),
    ("untyped_defs", "INTEGER"),
    ("side_effects", "JSON"),
    ("raises", "JSON"),
    ("complexity", "JSON"),
    ("covered_lines_ratio", "DOUBLE"),
    ("covered_defs_ratio", "DOUBLE"),
    ("config_refs", "JSON"),
    ("overlay_needed", "BOOLEAN"),
]
_INSERT_SQL = (
    "INSERT INTO modules VALUES ("
    "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(slots=True, frozen=True)
class DuckConn:
    """Connection metadata for enrichment DuckDB ingestion."""

    db_path: Path


def _duckdb() -> object:
    """Import duckdb on demand to keep it optional at runtime.

    Returns
    -------
    object
        DuckDB module ready for connections.
    """
    return gate_import("duckdb", purpose="enrichment analytics")


def ensure_schema(conn: DuckConn) -> None:
    """Create the ``modules`` table if it does not already exist."""
    duckdb = _duckdb()
    conn.db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(conn.db_path)) as con:  # type: ignore[reportAttributeAccessIssue]
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS modules (
                path TEXT PRIMARY KEY,
                docstring TEXT,
                doc_summary TEXT,
                repo_path TEXT,
                module_name TEXT,
                stable_id TEXT,
                doc_has_summary BOOLEAN,
                doc_param_parity BOOLEAN,
                doc_examples_present BOOLEAN,
                imports JSON,
                defs JSON,
                exports JSON,
                exports_declared JSON,
                outline_nodes JSON,
                scip_symbols JSON,
                parse_ok BOOLEAN,
                errors JSON,
                tags JSON,
                type_errors INTEGER,
                type_error_count INTEGER,
                doc_metrics JSON,
                doc_items JSON,
                annotation_ratio JSON,
                untyped_defs INTEGER,
                side_effects JSON,
                raises JSON,
                complexity JSON,
                covered_lines_ratio DOUBLE,
                covered_defs_ratio DOUBLE,
                config_refs JSON,
                overlay_needed BOOLEAN
            )
            """
        )


def ingest_modules_jsonl(conn: DuckConn, modules_jsonl: Path) -> int:
    """Load modules.jsonl rows into DuckDB, replacing existing paths.

    Parameters
    ----------
    conn : DuckConn
        DuckDB connection wrapper containing the database path. The connection
        is used to ensure the schema exists and to execute insert/delete queries.
    modules_jsonl : Path
        Path to the JSONL file containing module records. Each line must be a
        valid JSON object representing a ModuleRecord. Existing records with
        matching paths are deleted before insertion.

    Returns
    -------
    int
        Total number of rows now present in the ``modules`` table.
    """
    duckdb = _duckdb()
    ensure_schema(conn)
    with duckdb.connect(str(conn.db_path)) as con:  # type: ignore[reportAttributeAccessIssue]
        payloads = _load_json_rows(modules_jsonl)
        if not payloads:
            (count,) = con.execute("SELECT COUNT(*) FROM modules").fetchone()
            return int(count)
        path_values: set[str] = set()
        for payload in payloads:
            path_value = payload.get("path")
            if isinstance(path_value, str):
                path_values.add(path_value)
        paths = sorted(path_values)
        con.executemany("DELETE FROM modules WHERE path = ?", [(path,) for path in paths])
        insert_values = []
        for payload in payloads:
            row_values = []
            for name, col_type in _MODULE_COLUMNS:
                row_values.append(_coerce_value(payload.get(name), col_type))
            insert_values.append(tuple(row_values))
        con.executemany(_INSERT_SQL, insert_values)
        (count,) = con.execute("SELECT COUNT(*) FROM modules").fetchone()
    return int(count)


def _load_json_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    buffer: list[str] = []
    depth = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            buffer.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                rows.append(json.loads("".join(buffer)))
                buffer.clear()
                depth = 0
    return rows


def _coerce_value(value: object, col_type: str | None) -> object:
    if value is None:
        return None
    normalized = (col_type or "").upper()
    if "JSON" in normalized:
        return json.dumps(value)
    return value
