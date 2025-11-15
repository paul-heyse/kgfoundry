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
                  glob_pattern TEXT PRIMARY KEY,
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

        payload = [
            (
                row.symbol,
                row.display_name,
                row.kind,
                row.language,
                row.uri,
                row.start_line,
                row.start_col,
                row.end_line,
                row.end_col,
                row.chunk_id,
                row.docstring,
                row.signature,
            )
            for row in rows
        ]
        with self._manager.connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO symbol_defs(
                  symbol,
                  display_name,
                  kind,
                  language,
                  uri,
                  start_line,
                  start_col,
                  end_line,
                  end_col,
                  chunk_id,
                  docstring,
                  signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    def bulk_insert_occurrences(self, rows: Sequence[SymbolOccurrenceRow]) -> None:
        """Bulk load symbol occurrences."""
        if not rows:
            return
        with self._manager.connection() as conn:
            conn.executemany(
                """
                INSERT INTO symbol_occurrences(
                    symbol,
                    uri,
                    start_line,
                    start_col,
                    end_line,
                    end_col,
                    roles,
                    kind,
                    language,
                    chunk_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.symbol,
                        row.uri,
                        row.start_line,
                        row.start_col,
                        row.end_line,
                        row.end_col,
                        row.roles,
                        row.kind,
                        row.language,
                        row.chunk_id,
                    )
                    for row in rows
                ],
            )

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

    def fetch_symbol_defs(
        self,
        *,
        limit: int | None = None,
        kinds: Sequence[str] | None = None,
    ) -> list[SymbolDefRow]:
        """Return symbol definitions with stable chunk identifiers.

        Parameters
        ----------
        limit : int | None, optional
            Optional upper bound on the number of rows returned.
        kinds : Sequence[str] | None, optional
            When provided, restricts returned rows to the specified symbol kinds.

        Returns
        -------
        list[SymbolDefRow]
            Materialized symbol definition rows ordered by symbol identifier.
        """
        sql = (
            "SELECT symbol, display_name, kind, language, uri, start_line, start_col, "
            "end_line, end_col, chunk_id, docstring, signature "
            "FROM symbol_defs WHERE chunk_id IS NOT NULL"
        )
        params: list[object] = []
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            sql += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        sql += " ORDER BY symbol"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._manager.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            SymbolDefRow(
                symbol=row[0],
                display_name=row[1],
                kind=row[2],
                language=row[3],
                uri=row[4],
                start_line=row[5],
                start_col=row[6],
                end_line=row[7],
                end_col=row[8],
                chunk_id=int(row[9]),
                docstring=row[10],
                signature=row[11],
            )
            for row in rows
        ]
