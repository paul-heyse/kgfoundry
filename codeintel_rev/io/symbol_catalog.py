"""DuckDB symbol catalog writer."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from codeintel_rev.io.duckdb_manager import DuckDBManager


@dataclass(frozen=True)
class SymbolDefRow:
    """Immutable row describing a symbol definition."""

    symbol: str
    display_name: str
    kind: str
    language: str
    uri: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    chunk_id: int
    docstring: str | None = None
    signature: str | None = None


@dataclass(frozen=True)
class SymbolOccurrenceRow:
    """Service row for individual symbol occurrences."""

    symbol: str
    uri: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    roles: int
    kind: str | None
    language: str
    chunk_id: int


class SymbolCatalog:
    """Writer for symbol metadata tables alongside `chunks`."""

    def __init__(self, manager: DuckDBManager) -> None:
        self._manager = manager

    def ensure_schema(self) -> None:
        """Ensure symbol tables and indexes exist in DuckDB."""
        with self._manager.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_defs(
                  symbol TEXT PRIMARY KEY,
                  display_name TEXT,
                  kind TEXT,
                  language TEXT,
                  uri TEXT,
                  start_line INTEGER,
                  start_col INTEGER,
                  end_line INTEGER,
                  end_col INTEGER,
                  chunk_id INTEGER,
                  docstring TEXT,
                  signature TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbol_defs_name ON symbol_defs(display_name)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_defs_uri ON symbol_defs(uri)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_occurrences(
                  symbol TEXT,
                  uri TEXT,
                  start_line INTEGER,
                  start_col INTEGER,
                  end_line INTEGER,
                  end_col INTEGER,
                  roles INTEGER,
                  kind TEXT,
                  language TEXT,
                  chunk_id INTEGER
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_occ_sym ON symbol_occurrences(symbol)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_occ_uri_pos ON symbol_occurrences(uri, start_line)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_symbols(
                  chunk_id INTEGER,
                  symbol TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_symbols_chunk ON chunk_symbols(chunk_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_symbols_sym ON chunk_symbols(symbol)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS path_weights(
                  glob TEXT PRIMARY KEY,
                  weight DOUBLE
                )"""
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kind_weights(
                  kind TEXT PRIMARY KEY,
                  weight DOUBLE
                )"""
            )

    def upsert_symbol_defs(self, rows: Sequence[SymbolDefRow]) -> None:
        """Insert or replace symbol definitions in bulk."""
        if not rows:
            return

        with self._manager.connection() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "CREATE TEMP TABLE _defs AS SELECT * FROM (SELECT ''::TEXT AS symbol) WHERE 1=0"
                )
                conn.register("_tmp_defs", rows)
                conn.execute("INSERT OR REPLACE INTO symbol_defs SELECT * FROM _tmp_defs")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def bulk_insert_occurrences(self, rows: Sequence[SymbolOccurrenceRow]) -> None:
        """Bulk load symbol occurrences."""
        if not rows:
            return
        with self._manager.connection() as conn:
            conn.register("_tmp_occs", rows)
            conn.execute("INSERT INTO symbol_occurrences SELECT * FROM _tmp_occs")

    def bulk_insert_chunk_symbols(self, pairs: Iterable[tuple[int, str]]) -> None:
        """Associate chunks with the symbols they contain."""
        pairs = list(pairs)
        if not pairs:
            return
        with self._manager.connection() as conn:
            conn.register(
                "_tmp_pairs",
                [{"chunk_id": chunk_id, "symbol": symbol} for chunk_id, symbol in pairs],
            )
            conn.execute("INSERT INTO chunk_symbols SELECT * FROM _tmp_pairs")
