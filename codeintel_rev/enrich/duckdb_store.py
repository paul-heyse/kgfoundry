# SPDX-License-Identifier: MIT
"""Utilities for loading enrichment artifacts into DuckDB."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from codeintel_rev.typing import gate_import

__all__ = ["DuckConn", "DuckDBIngestContext", "ensure_schema", "ingest_modules_jsonl"]

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


def _parse_pragmas(spec: str) -> tuple[tuple[str, str], ...]:
    settings: list[tuple[str, str]] = []
    if not spec:
        return ()
    for entry in spec.split(","):
        if "=" not in entry:
            continue
        key, value = (token.strip() for token in entry.split("=", 1))
        if not key or not value or not _PRAGMA_KEY_PATTERN.fullmatch(key):
            continue
        literal = value if value.replace(".", "", 1).isdigit() else f"'{value}'"
        settings.append((key, literal))
    return tuple(settings)


_PRAGMA_SETTINGS = _parse_pragmas(_DUCKDB_PRAGMAS)

if TYPE_CHECKING:
    import duckdb as duckdb_module

    DuckDBConnection = duckdb_module.DuckDBPyConnection
else:  # pragma: no cover - runtime duckdb import is optional
    DuckDBConnection = Any


class _DuckDBModule(Protocol):
    """Protocol describing the subset of duckdb module APIs we rely on."""

    def connect(
        self, database: str | None = ..., *args: object, **kwargs: object
    ) -> DuckDBConnection:
        """Create a DuckDB connection to the specified database.

        Parameters
        ----------
        database : str | None, optional
            Path to database file. If None, creates an in-memory database.
        *args : object
            Additional positional arguments passed to duckdb.connect().
        **kwargs : object
            Additional keyword arguments passed to duckdb.connect().

        Returns
        -------
        DuckDBConnection
            DuckDB connection object ready for query execution.
        """
        ...


@dataclass(slots=True, frozen=True)
class DuckConn:
    """Connection metadata for enrichment DuckDB ingestion."""

    db_path: Path


@dataclass(slots=True, frozen=True)
class DuckDBIngestContext:
    """Dependency providers and options for DuckDB ingestion routines."""

    duckdb_module: _DuckDBModule
    use_native_json: bool = True
    pragmas: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_env(cls) -> DuckDBIngestContext:
        """Build a context using module defaults and environment toggles.

        Returns
        -------
        DuckDBIngestContext
            Context configured with the project-wide DuckDB module and env toggles.
        """
        return cls(duckdb_module=_duckdb(), use_native_json=_USE_NATIVE_JSON, pragmas=_PRAGMA_SETTINGS)


def _duckdb() -> _DuckDBModule:
    """Import duckdb on demand to keep it optional at runtime.

    Returns
    -------
    _DuckDBModule
        DuckDB module ready for connections.
    """
    module = gate_import("duckdb", purpose="enrichment analytics")
    return cast("_DuckDBModule", module)


def ensure_schema(conn: DuckConn, *, context: DuckDBIngestContext | None = None) -> None:
    """Create the ``modules`` table if it does not already exist."""
    ctx = context or DuckDBIngestContext.from_env()
    duckdb_module = ctx.duckdb_module
    conn.db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb_module.connect(str(conn.db_path)) as con:
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


def ingest_modules_jsonl(
    conn: DuckConn,
    modules_jsonl: Path,
    *,
    context: DuckDBIngestContext | None = None,
) -> int:
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
    context : DuckDBIngestContext | None, optional
        Dependency overrides controlling which DuckDB module to use, whether to
        leverage DuckDB's native JSON ingestion, and any pragmas to apply. When
        ``None``, defaults to :meth:`DuckDBIngestContext.from_env`.

    Returns
    -------
    int
        Total number of rows now present in the ``modules`` table.
    """
    ctx = context or DuckDBIngestContext.from_env()
    duckdb_module = ctx.duckdb_module
    ensure_schema(conn, context=ctx)
    with duckdb_module.connect(str(conn.db_path)) as con:
        _apply_pragmas(con, ctx.pragmas)
        if ctx.use_native_json:
            _ingest_via_native_json(con, modules_jsonl)
        else:
            _ingest_via_python(con, modules_jsonl)
        row = con.execute("SELECT COUNT(*) FROM modules").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


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


def _apply_pragmas(con: DuckDBConnection, pragmas: tuple[tuple[str, str], ...]) -> None:
    if not pragmas:
        return
    for key, literal in pragmas:
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
