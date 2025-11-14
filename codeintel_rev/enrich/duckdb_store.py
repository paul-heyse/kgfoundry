# SPDX-License-Identifier: MIT
"""Utilities for loading enrichment artifacts into DuckDB."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeintel_rev.typing import gate_import

__all__ = ["DuckConn", "ensure_schema", "ingest_modules_jsonl"]

_USE_NATIVE_JSON = os.getenv("USE_DUCKDB_JSON", "1") not in {"0", "false", "False"}
_DUCKDB_PRAGMAS = os.getenv("DUCKDB_PRAGMAS", "")
_PRAGMA_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
_MODULE_COLUMN_NAMES: Sequence[str] = tuple(name for name, _ in _MODULE_COLUMNS)

if TYPE_CHECKING:
    import duckdb as duckdb_module

    DuckDBConnection = duckdb_module.DuckDBPyConnection
else:  # pragma: no cover - runtime duckdb import is optional
    DuckDBConnection = Any


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
        _apply_pragmas(con)
        if _USE_NATIVE_JSON:
            _ingest_via_native_json(con, modules_jsonl)
        else:
            _ingest_via_python(con, modules_jsonl)
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


def _apply_pragmas(con: DuckDBConnection) -> None:
    if not _DUCKDB_PRAGMAS:
        return
    for entry in _DUCKDB_PRAGMAS.split(","):
        if "=" not in entry:
            continue
        key, value = (token.strip() for token in entry.split("=", 1))
        if not key or not value or not _PRAGMA_KEY_PATTERN.fullmatch(key):
            continue
        literal = value if value.replace(".", "", 1).isdigit() else f"'{value}'"
        con.execute(f"PRAGMA {key}={literal}")


def _ingest_via_native_json(con: DuckDBConnection, modules_jsonl: Path) -> None:
    con.execute("DROP TABLE IF EXISTS modules_stage")
    con.execute(
        "CREATE TEMP TABLE modules_stage AS SELECT * FROM read_json_auto(?)",
        (str(modules_jsonl),),
    )
    existing_columns = {
        row[1] for row in con.execute("PRAGMA table_info('modules_stage')").fetchall()
    }
    for name, col_type in _MODULE_COLUMNS:
        if name not in existing_columns:
            con.execute(f"ALTER TABLE modules_stage ADD COLUMN {name} {col_type}")
    assignments = ", ".join(f"{name}=s.{name}" for name in _MODULE_COLUMN_NAMES)
    insert_columns = ", ".join(_MODULE_COLUMN_NAMES)
    insert_values = ", ".join(f"s.{name}" for name in _MODULE_COLUMN_NAMES)
    merge_template = """
        MERGE INTO modules t
        USING modules_stage s
        ON t.path = s.path
        WHEN MATCHED THEN UPDATE SET __ASSIGNMENTS__
        WHEN NOT MATCHED THEN INSERT (__COLUMNS__) VALUES (__VALUES__)
        """
    merge_sql = (
        merge_template.replace("__ASSIGNMENTS__", assignments)
        .replace("__COLUMNS__", insert_columns)
        .replace("__VALUES__", insert_values)
    )
    con.execute(merge_sql)
    con.execute("DROP TABLE IF EXISTS modules_stage")


def _ingest_via_python(con: DuckDBConnection, modules_jsonl: Path) -> None:
    payloads = _load_json_rows(modules_jsonl)
    if not payloads:
        return
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
