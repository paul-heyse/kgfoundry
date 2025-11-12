"""DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Any, Self, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_manager import (
    DuckDBManager,
    DuckDBQueryBuilder,
    DuckDBQueryOptions,
)
from codeintel_rev.io.parquet_store import extract_embeddings
from codeintel_rev.mcp_server.scope_utils import (
    LANGUAGE_EXTENSIONS,
    path_matches_glob,
)
from codeintel_rev.observability.timeline import current_timeline
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import build_histogram

if TYPE_CHECKING:
    import duckdb
    import numpy as np
else:
    duckdb = cast("duckdb", LazyModule("duckdb", "DuckDB catalog operations"))
    np = cast("np", LazyModule("numpy", "DuckDB catalog embeddings"))

LOGGER = get_logger(__name__)


def _log_extra(**kwargs: object) -> dict[str, object]:
    """Return structured log extras for catalog events.

    Returns
    -------
    dict[str, object]
        Structured logging payload.
    """
    return {"component": "duckdb_catalog", **kwargs}


# Prometheus metrics for scope filtering
_scope_filter_duration_seconds = build_histogram(
    "codeintel_scope_filter_duration_seconds",
    "Time to apply scope filters",
    labelnames=("filter_type",),
)
_catalog_view_bootstrap_seconds = build_histogram(
    "codeintel_duckdb_view_bootstrap_seconds",
    "Time spent ensuring DuckDB catalog views are installed",
)

_EMPTY_CHUNKS_SELECT = """
SELECT
    CAST(NULL AS BIGINT) AS id,
    CAST(NULL AS VARCHAR) AS uri,
    CAST(NULL AS INTEGER) AS start_line,
    CAST(NULL AS INTEGER) AS end_line,
    CAST(NULL AS BIGINT) AS start_byte,
    CAST(NULL AS BIGINT) AS end_byte,
    CAST(NULL AS VARCHAR) AS preview,
    CAST(NULL AS VARCHAR) AS content,
    CAST(NULL AS VARCHAR) AS lang,
            CAST(NULL AS FLOAT[]) AS embedding
WHERE 1 = 0
"""


@dataclass(frozen=True)
class _ScopeFilterSpec:
    """Structured scope filter metadata used during scoped queries."""

    chunk_ids: tuple[int, ...]
    simple_include_globs: tuple[str, ...] | None
    simple_exclude_globs: tuple[str, ...] | None
    complex_include_patterns: tuple[str, ...]
    complex_exclude_patterns: tuple[str, ...]
    language_extensions: frozenset[str]

    @property
    def has_complex_globs(self) -> bool:
        """Return ``True`` when complex include/exclude patterns exist."""
        return bool(self.complex_include_patterns or self.complex_exclude_patterns)


class DuckDBCatalog:
    """DuckDB catalog for querying chunks.

    Parameters
    ----------
    db_path : Path
        DuckDB database path.
    vectors_dir : Path
        Directory containing Parquet files.
    materialize : bool, optional
        When ``True``, chunk metadata is materialized into a persisted DuckDB
        table (``chunks_materialized``) with a secondary index on ``uri``. When
        ``False`` (default), the catalog exposes Parquet files through a view for
        zero-copy queries.
    manager : DuckDBManager | None, optional
        DuckDB connection manager instance. If ``None``, creates a new manager
        with default configuration. Defaults to ``None``.
    log_queries : bool | None, optional
        Enable debug logging of executed SQL statements when ``True``. Defaults to
        ``None`` which inherits the global logging configuration.
    """

    def __init__(
        self,
        db_path: Path,
        vectors_dir: Path,
        *,
        materialize: bool = False,
        manager: DuckDBManager | None = None,
        log_queries: bool | None = None,
    ) -> None:
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.materialize = materialize
        manager = manager or DuckDBManager(db_path)
        self._manager = manager
        self._query_builder = DuckDBQueryBuilder()
        self._embedding_dim_cache: int | None = None
        self._init_lock = Lock()
        self._views_ready = False
        self._log_queries = log_queries if log_queries is not None else manager.config.log_queries
        self._root_dir = vectors_dir.parent.resolve()
        default_idmap = (self._root_dir / "faiss/faiss_idmap.parquet").resolve()
        self._idmap_path = default_idmap

    def open(self) -> None:
        """Ensure catalog views are initialized."""
        self._ensure_ready()

    def close(self) -> None:
        """No-op for compatibility; connections are per-use via the manager."""
        self._embedding_dim_cache = None

    def __enter__(self) -> Self:
        """Enter context manager.

        Returns
        -------
        Self
            The catalog instance with an active DuckDB connection.
        """
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit context manager."""
        self.close()

    @property
    def manager(self) -> DuckDBManager:
        """Return the underlying DuckDB manager."""
        return self._manager

    def _ensure_ready(self) -> None:
        """Initialize catalog views once in a threadsafe manner."""
        if self._views_ready:
            return
        with self._init_lock:
            if self._views_ready:
                return
            with self._manager.connection() as conn:
                self._ensure_views(conn)
            self._views_ready = True

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a configured DuckDB connection.

        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection configured with catalog pragmas and ready for queries.
        """
        self._ensure_ready()
        with self._manager.connection() as conn:
            yield conn

    def _log_query(self, sql: str, params: object | None = None) -> None:
        """Emit debug log for executed DuckDB statement when enabled."""
        if not self._log_queries:
            return
        LOGGER.debug(
            "duckdb_query",
            extra={
                "sql": sql.strip(),
                "params": params,
                "duckdb_path": str(self.db_path),
            },
        )

    def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create required views and tables to hydrate chunk metadata."""
        start = perf_counter()
        try:
            self._install_chunks_view(conn)
            self._install_optional_views(conn)
            self._ensure_idmap_tables(conn)
            self._ensure_faiss_idmap_view(conn, None)
            self._ensure_faiss_join_view(conn)
        finally:
            _catalog_view_bootstrap_seconds.observe(max(perf_counter() - start, 0.0))

    def _install_chunks_view(self, conn: duckdb.DuckDBPyConnection) -> None:
        chunks_ready = self._relation_exists(conn, "chunks")
        if chunks_ready:
            return
        parquet_pattern = str(self.vectors_dir / "**/*.parquet")
        parquet_exists = any(self.vectors_dir.rglob("*.parquet"))

        if self.materialize:
            if parquet_exists:
                sql = """
                    CREATE OR REPLACE TABLE chunks_materialized AS
                    SELECT * FROM read_parquet(?)
                    """
                self._log_query(sql, [parquet_pattern])
                conn.execute(sql, [parquet_pattern])
            else:
                sql = f"CREATE OR REPLACE TABLE chunks_materialized AS {_EMPTY_CHUNKS_SELECT}"
                self._log_query(sql, None)
                conn.execute(sql)

            view_sql = "CREATE OR REPLACE VIEW chunks AS SELECT * FROM chunks_materialized"
            self._log_query(view_sql, None)
            conn.execute(view_sql)

            index_sql = (
                "CREATE INDEX IF NOT EXISTS idx_chunks_materialized_uri ON chunks_materialized(uri)"
            )
            self._log_query(index_sql, None)
            conn.execute(index_sql)
            LOGGER.info(
                "Materialized DuckDB chunks table",
                extra={
                    "materialized": True,
                    "parquet_found": parquet_exists,
                    "db_path": str(self.db_path),
                },
            )
            return

        if parquet_exists:
            sql = "SELECT * FROM read_parquet(?)"
            self._log_query(sql, [parquet_pattern])
            relation = conn.sql(sql, params=[parquet_pattern])
            relation.create_view("chunks", replace=True)
        else:
            sql = f"CREATE OR REPLACE VIEW chunks AS {_EMPTY_CHUNKS_SELECT}"
            self._log_query(sql, None)
            conn.execute(sql)
        LOGGER.debug(
            "Configured DuckDB chunks view",
            extra={
                "materialized": False,
                "parquet_found": parquet_exists,
                "db_path": str(self.db_path),
            },
        )

    def _install_optional_views(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._install_parquet_view(conn, "modules", self._root_dir / "modules/modules.parquet")
        self._install_parquet_view(
            conn,
            "scip_occurrences",
            self._root_dir / "scip/scip_occurrences.parquet",
        )
        self._install_parquet_view(conn, "ast_nodes", self._root_dir / "ast/ast_nodes.parquet")
        self._install_parquet_view(conn, "cst_nodes", self._root_dir / "cst/cst_nodes.parquet")
        self._install_chunk_symbols_view(conn)

    def _install_parquet_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
        source: Path,
    ) -> bool:
        if not source.exists():
            return False
        sql = "SELECT * FROM read_parquet(?)"
        params = [str(source)]
        self._log_query(sql, params)
        relation = conn.sql(sql, params=params)
        relation.create_view(view_name, replace=True)
        LOGGER.info(
            "Configured DuckDB view",
            extra=_log_extra(view=view_name, source=str(source)),
        )
        return True

    @staticmethod
    def _install_chunk_symbols_view(conn: duckdb.DuckDBPyConnection) -> None:
        try:
            conn.execute(
                """
                CREATE OR REPLACE VIEW v_chunk_symbols AS
                SELECT
                    c.id AS chunk_id,
                    symbol
                FROM chunks AS c,
                     LATERAL UNNEST(
                        COALESCE(c.symbols, []::VARCHAR[])
                     ) AS t(symbol)
                """
            )
            LOGGER.info("Configured DuckDB view", extra=_log_extra(view="v_chunk_symbols"))
        except duckdb.Error as exc:  # pragma: no cover - defensive fallback for legacy schemas
            LOGGER.debug(
                "Skipping v_chunk_symbols view",
                extra=_log_extra(error=str(exc)),
            )

    @staticmethod
    def _ensure_idmap_tables(conn: duckdb.DuckDBPyConnection) -> None:
        """Ensure IDMap materialization tables exist for joins and checksums."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faiss_idmap_mat (
                faiss_row   BIGINT,
                external_id BIGINT,
                source      TEXT
            )
            """
        )
        conn.execute("ALTER TABLE faiss_idmap_mat ADD COLUMN IF NOT EXISTS source TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faiss_idmap_mat_meta (
                checksum   TEXT NOT NULL,
                row_count  BIGINT NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )

    @staticmethod
    def _ensure_faiss_join_view(conn: duckdb.DuckDBPyConnection) -> None:
        """Expose chunks joined with FAISS ID map for deterministic hydration."""
        conn.execute(
            """
            CREATE OR REPLACE VIEW v_faiss_join AS
            SELECT
                c.*,
                f.faiss_row,
                f.source AS faiss_source
            FROM chunks AS c
            LEFT JOIN faiss_idmap AS f
              ON f.external_id = c.id
            """
        )

    def _ensure_faiss_idmap_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        override_path: Path | None,
    ) -> None:
        path = override_path or self._idmap_path
        if path.exists():
            sql = "SELECT * FROM read_parquet(?)"
            params = [str(path)]
            self._log_query(sql, params)
            relation = conn.sql(sql, params=params)
            relation.create_view("faiss_idmap", replace=True)
            LOGGER.info(
                "Configured DuckDB view",
                extra=_log_extra(view="faiss_idmap", source=str(path)),
            )
            return

        if self._relation_exists(conn, "faiss_idmap_mat"):
            conn.execute(
                """
                CREATE OR REPLACE VIEW faiss_idmap AS
                SELECT
                    faiss_row,
                    external_id,
                    COALESCE(source, 'materialized') AS source
                FROM faiss_idmap_mat
                """
            )
            LOGGER.info(
                "Configured DuckDB view",
                extra=_log_extra(view="faiss_idmap", source="faiss_idmap_mat"),
            )
            return

        conn.execute(
            """
            CREATE OR REPLACE VIEW faiss_idmap AS
            SELECT
                CAST(NULL AS BIGINT) AS faiss_row,
                CAST(NULL AS BIGINT) AS external_id,
                CAST(NULL AS TEXT)  AS source
            WHERE 1 = 0
            """
        )

    def ensure_faiss_idmap_views(self, idmap_path: Path | None = None) -> None:
        """Install/refresh FAISS id map views from a specific Parquet file."""
        with self.connection() as conn:
            self._ensure_faiss_idmap_view(conn, idmap_path)
            self._ensure_faiss_join_view(conn)

    def set_idmap_path(self, path: Path) -> None:
        """Override the FAISS id map path used for view installation."""
        self._idmap_path = path.resolve()

    @staticmethod
    def _relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
        """Return True when a table or view with ``name`` exists in the main schema.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection used to inspect the catalog.
        name : str
            Table or view name to look up within the ``main`` schema.

        Returns
        -------
        bool
            ``True`` when the relation exists, otherwise ``False``.
        """
        row = conn.execute(
            """
            SELECT EXISTS(
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name = ?
                UNION ALL
                SELECT 1
                FROM information_schema.views
                WHERE table_schema = 'main'
                  AND table_name = ?
            )
            """,
            [name, name],
        ).fetchone()
        return bool(row and row[0])

    @staticmethod
    def relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
        """Return True when a table or view exists (public wrapper).

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to inspect.
        name : str
            Table or view name to look up.

        Returns
        -------
        bool
            ``True`` when the relation exists in schema ``main``.
        """
        return DuckDBCatalog._relation_exists(conn, name)

    @staticmethod
    def _file_checksum(path: Path) -> str:
        """Return SHA-256 checksum for ``path``.

        Returns
        -------
        str
            Hex digest representing the file contents.
        """
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def refresh_faiss_idmap_mat_if_changed(self, idmap_parquet: Path) -> dict[str, Any]:
        """Materialize FAISS ID map when the Parquet sidecar content changes.

        Parameters
        ----------
        idmap_parquet : Path
            Parquet file containing ``faiss_row`` and ``external_id`` columns.

        Returns
        -------
        dict[str, Any]
            Summary dictionary with ``refreshed``, ``checksum``, and ``rows`` keys.
        """
        checksum = self._file_checksum(idmap_parquet)
        stats: dict[str, Any]
        with self._manager.connection() as conn:
            self._ensure_views(conn)
            row = conn.execute(
                """
                SELECT checksum, row_count
                  FROM faiss_idmap_mat_meta
              ORDER BY updated_at DESC
                 LIMIT 1
                """
            ).fetchone()
            if row and row[0] == checksum:
                rows = int(row[1])
                return {"refreshed": False, "checksum": checksum, "rows": rows}

            conn.execute("DELETE FROM faiss_idmap_mat")
            conn.execute(
                """
                INSERT INTO faiss_idmap_mat (faiss_row, external_id, source)
                SELECT
                    faiss_row,
                    external_id,
                    COALESCE(source, 'parquet') AS source
                FROM read_parquet(?)
                """,
                [str(idmap_parquet)],
            )
            count_row = conn.execute("SELECT COUNT(*) FROM faiss_idmap_mat").fetchone()
            row_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
            conn.execute(
                """
                INSERT INTO faiss_idmap_mat_meta(checksum, row_count, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                [checksum, row_count],
            )
            stats = {"refreshed": True, "checksum": checksum, "rows": row_count}
            self._ensure_faiss_idmap_view(conn, idmap_parquet)
            self._ensure_faiss_join_view(conn)

        LOGGER.info(
            "faiss_idmap_materialized", extra=_log_extra(rows=stats["rows"], checksum=checksum)
        )
        return stats

    def sample_query_vectors(self, limit: int = 64) -> list[tuple[int, np.ndarray]]:
        """Return (chunk_id, vector) samples for offline evaluation.

        Parameters
        ----------
        limit : int, optional
            Maximum number of vectors to return, by default 64.

        Returns
        -------
        list[tuple[int, numpy.ndarray]]
            Chunk identifiers paired with embedding vectors.
        """
        if limit <= 0:
            return []
        with self.connection() as conn:
            result = conn.execute(
                """
                SELECT id, embedding
                  FROM chunks
                 WHERE embedding IS NOT NULL
                 LIMIT ?
                """,
                [int(limit)],
            )
            table = result.fetch_arrow_table()

        vectors = extract_embeddings(table)
        ids = table.column("id").to_pylist()

        samples: list[tuple[int, np.ndarray]] = []
        for idx, chunk_id in enumerate(ids):
            if chunk_id is None:
                continue
            samples.append((int(chunk_id), vectors[idx]))
        return samples

    def query_by_ids(self, ids: Sequence[int]) -> list[dict]:
        """Query chunks by their unique IDs.

        Retrieves chunk metadata (text, URI, line numbers, etc.) for a list of
        chunk IDs. This is typically used after a FAISS search returns chunk IDs
        to hydrate the results with full chunk information.

        The function constructs a SQL IN clause to efficiently fetch multiple
        chunks in a single query. Results are returned as dictionaries with column
        names as keys, matching the Parquet schema.

        Parameters
        ----------
        ids : Sequence[int]
            Sequence of chunk IDs to retrieve. IDs must exist in the chunks table.
            Empty sequence returns empty list.

        Returns
        -------
        list[dict]
            List of chunk records as dictionaries. Each dict contains all columns
            from the chunks Parquet file (id, uri, text, start_line, end_line,
            symbols, etc.). Returns empty list if no IDs provided or no matches.

        """
        if not ids:
            return []

        timeline = current_timeline()
        start_time = None
        if timeline is not None:
            start_time = perf_counter()
            timeline.event(
                "duckdb.hydrate.start",
                "catalog",
                attrs={"asked_for": len(ids)},
            )

        sql = """
            SELECT c.*
            FROM chunks AS c
            JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                ON c.id = ids.id
            ORDER BY ids.position
            """
        params = [list(ids)]
        with self.connection() as conn:
            self._log_query(sql, params)
            relation = conn.execute(sql, params)
            rows = relation.fetchall()
            cols = [desc[0] for desc in relation.description]
        payload = [dict(zip(cols, row, strict=True)) for row in rows]
        if timeline is not None:
            duration_ms = (
                int((perf_counter() - start_time) * 1000) if start_time is not None else None
            )
            timeline.event(
                "duckdb.hydrate.end",
                "catalog",
                attrs={
                    "returned": len(payload),
                    "missing": max(0, len(ids) - len(payload)),
                    "duration_ms": duration_ms,
                },
            )
        return payload

    def query_by_filters(
        self,
        ids: Sequence[int],
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> list[dict]:
        """Query chunks by IDs with path and language filtering.

        Retrieves chunk metadata for a list of chunk IDs, applying optional filters
        for path patterns (include/exclude globs) and programming languages. This
        method is used after FAISS search to filter results by scope constraints.

        Filtering Strategy:
        - Simple globs (e.g., `*.py`, `src/**`) are converted to SQL `LIKE` patterns
          for efficient database-side filtering.
        - Complex globs (e.g., `src/**/test_*.py`) fall back to Python `fnmatch`
          post-filtering after SQL query execution.
        - Language filtering uses file extension mapping (e.g., `python` → `.py`, `.pyi`).

        Parameters
        ----------
        ids : Sequence[int]
            Sequence of chunk IDs to retrieve. Empty sequence returns empty list.
        include_globs : list[str] | None, optional
            Glob patterns to include. Chunks must match at least one pattern.
            Empty list means "include all" (no filtering). Defaults to None.
        exclude_globs : list[str] | None, optional
            Glob patterns to exclude. Chunks matching any pattern are removed.
            Empty list means "exclude none". Defaults to None.
        languages : list[str] | None, optional
            Programming language names (e.g., ["python", "typescript"]).
            Filters chunks by file extension. Defaults to None.

        Returns
        -------
        list[dict]
            List of filtered chunk records as dictionaries. Each dict contains all
            columns from the chunks Parquet file. Results preserve input ID order
            (via JOIN with UNNEST ordinality). Returns empty list if no IDs provided
            or all chunks filtered out.

        Examples
        --------
        Filter by language:

        >>> catalog.query_by_filters([1, 2, 3], languages=["python"])
        [{'id': 1, 'uri': 'src/main.py', ...}, {'id': 2, 'uri': 'src/utils.py', ...}]

        Filter by include globs:

        >>> catalog.query_by_filters([1, 2, 3], include_globs=["src/**/*.py"])
        [{'id': 1, 'uri': 'src/main.py', ...}]

        Combined filters:

        >>> catalog.query_by_filters(
        ...     [1, 2, 3],
        ...     include_globs=["**/*.py"],
        ...     exclude_globs=["**/test_*.py"],
        ...     languages=["python"],
        ... )
        [{'id': 1, 'uri': 'src/main.py', ...}]

        Notes
        -----
        SQL LIKE Pattern Conversion:
        - `**/*.py` → `%.py` (matches any path ending in .py)
        - `src/**` → `src/%` (matches paths starting with src/)
        - `*.py` → `%.py` (same as **/*.py in our implementation)

        Complex Glob Detection:
        - Patterns with `**` in the middle (e.g., `src/**/test_*.py`) are detected
          as complex and use Python post-filtering.
        - Patterns with bracket expressions `[...]` or `[!...]` use Python filtering.
        - Simple prefix/suffix patterns use SQL LIKE for performance.

        Language Extension Mapping:
        - Uses `LANGUAGE_EXTENSIONS` from `scope_utils` module.
        - Unknown languages are silently ignored (no error raised).
        - Extension matching is case-insensitive (normalizes to lowercase).

        Performance:
        - SQL filtering is preferred for large result sets (avoids transferring
          filtered-out chunks from database).
        - Python post-filtering adds ~1-2ms overhead per 1000 chunks.
        - Consider adding index on `uri` column for faster LIKE queries (see Task 14).
        """
        if not ids:
            return []

        start_time = perf_counter()
        spec = self._build_scope_filter_spec(
            ids,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            languages=languages,
        )

        if languages and not spec.language_extensions:
            self._observe_scope_filter_duration(start_time, include_globs, exclude_globs, languages)
            return []

        options = DuckDBQueryOptions(
            include_globs=spec.simple_include_globs,
            exclude_globs=spec.simple_exclude_globs,
            select_columns=("c.*",),
            preserve_order=True,
        )

        sql, sql_params = self._query_builder.build_filter_query(
            chunk_ids=spec.chunk_ids,
            options=options,
        )

        with self.connection() as conn:
            relation = conn.execute(sql, sql_params)
            rows = relation.fetchall()
            cols = [desc[0] for desc in relation.description]
        results = [dict(zip(cols, row, strict=True)) for row in rows]

        results = self._apply_complex_glob_filters(
            results,
            spec.complex_include_patterns,
            spec.complex_exclude_patterns,
        )
        results = self._apply_language_filters(results, spec.language_extensions)

        self._observe_scope_filter_duration(start_time, include_globs, exclude_globs, languages)
        return results

    def _build_scope_filter_spec(
        self,
        ids: Sequence[int],
        *,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        languages: list[str] | None,
    ) -> _ScopeFilterSpec:
        """Categorize scope filters and language extensions for later processing.

        Parameters
        ----------
        ids : Sequence[int]
            Chunk identifiers provided by FAISS.
        include_globs : list[str] | None
            Glob patterns to include via SQL LIKE.
        exclude_globs : list[str] | None
            Glob patterns to exclude via SQL LIKE.
        languages : list[str] | None
            Language names for extension-based filtering.

        Returns
        -------
        _ScopeFilterSpec
            Structured metadata describing how to materialize the query.
        """
        simple_include_globs: list[str] = []
        complex_include_patterns: list[str] = []
        simple_exclude_globs: list[str] = []
        complex_exclude_patterns: list[str] = []

        for patterns, target_simple, target_complex in (
            (include_globs, simple_include_globs, complex_include_patterns),
            (exclude_globs, simple_exclude_globs, complex_exclude_patterns),
        ):
            if not patterns:
                continue
            for pattern in patterns:
                if self._is_simple_glob(pattern):
                    target_simple.append(pattern)
                else:
                    target_complex.append(pattern)

        language_extensions: set[str] = set()
        if languages:
            for lang in languages:
                extensions = LANGUAGE_EXTENSIONS.get(lang.lower(), [])
                language_extensions.update(ext.lower() for ext in extensions)

        chunk_ids = tuple(int(chunk_id) for chunk_id in ids)

        return _ScopeFilterSpec(
            chunk_ids=chunk_ids,
            simple_include_globs=(tuple(simple_include_globs) if simple_include_globs else None),
            simple_exclude_globs=(tuple(simple_exclude_globs) if simple_exclude_globs else None),
            complex_include_patterns=tuple(complex_include_patterns),
            complex_exclude_patterns=tuple(complex_exclude_patterns),
            language_extensions=frozenset(language_extensions),
        )

    @staticmethod
    def _apply_complex_glob_filters(
        results: list[dict],
        include_patterns: tuple[str, ...],
        exclude_patterns: tuple[str, ...],
    ) -> list[dict]:
        """Run Python filtering for complex glob patterns not expressible in SQL.

        This method filters results by applying include and exclude glob patterns
        to the URI field of each result dictionary. Patterns that cannot be
        efficiently expressed in SQL (e.g., complex wildcards, multiple patterns)
        are handled here using Python's path matching logic.

        Parameters
        ----------
        results : list[dict]
            List of result dictionaries, each containing at least a "uri" key.
        include_patterns : tuple[str, ...]
            Glob patterns that URIs must match to be included. Empty tuple means
            no inclusion filter is applied.
        exclude_patterns : tuple[str, ...]
            Glob patterns that URIs must not match to be included. Empty tuple
            means no exclusion filter is applied.

        Returns
        -------
        list[dict]
            Filtered results matching include/exclude glob patterns. Results
            matching exclude patterns or not matching include patterns are removed.
        """
        if not include_patterns and not exclude_patterns:
            return results

        filtered_results: list[dict] = []
        for chunk in results:
            uri = chunk.get("uri", "")
            if not isinstance(uri, str):
                continue

            if include_patterns and not any(
                path_matches_glob(uri, pattern) for pattern in include_patterns
            ):
                continue

            if exclude_patterns and any(
                path_matches_glob(uri, pattern) for pattern in exclude_patterns
            ):
                continue

            filtered_results.append(chunk)

        return filtered_results

    @staticmethod
    def _apply_language_filters(
        results: list[dict],
        language_extensions: frozenset[str],
    ) -> list[dict]:
        """Filter results by normalized file extensions.

        This method filters results to include only those whose URI ends with
        one of the specified language extensions. Extensions are matched
        case-insensitively against the lowercase URI.

        Parameters
        ----------
        results : list[dict]
            List of result dictionaries, each containing at least a "uri" key.
        language_extensions : frozenset[str]
            Set of normalized file extensions (e.g., {".py", ".js", ".ts"}).
            Extensions should include the leading dot. Empty set means no
            language filter is applied.

        Returns
        -------
        list[dict]
            Filtered results matching language extensions. Only results whose
            URI ends with one of the specified extensions are included.
        """
        if not language_extensions:
            return results

        filtered_results: list[dict] = []
        for chunk in results:
            uri = chunk.get("uri", "")
            if not isinstance(uri, str):
                continue
            uri_lower = uri.lower()
            if any(uri_lower.endswith(ext) for ext in language_extensions):
                filtered_results.append(chunk)
        return filtered_results

    def _observe_scope_filter_duration(
        self,
        start_time: float,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        languages: list[str] | None,
    ) -> None:
        """Record how long scope filtering took for observability."""
        duration = perf_counter() - start_time
        filter_type = self._determine_filter_type(include_globs, exclude_globs, languages)
        with suppress(ValueError):
            _scope_filter_duration_seconds.labels(filter_type=filter_type).observe(duration)

    @staticmethod
    def _determine_filter_type(
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        languages: list[str] | None,
    ) -> str:
        """Format the filter type label used for Prometheus metrics.

        Determines the type of scope filtering being applied based on the
        presence of glob patterns and language filters. Used to label metrics
        for observability.

        Parameters
        ----------
        include_globs : list[str] | None
            List of include glob patterns, or None if not specified.
        exclude_globs : list[str] | None
            List of exclude glob patterns, or None if not specified.
        languages : list[str] | None
            List of language filters, or None if not specified.

        Returns
        -------
        str
            Filter type label: "combined" (both globs and languages),
            "glob" (only glob patterns), "language" (only language filters),
            or "none" (no filters).
        """
        if include_globs or exclude_globs:
            return "combined" if languages else "glob"
        if languages:
            return "language"
        return "none"

    @staticmethod
    def _is_simple_glob(pattern: str) -> bool:
        """Check if glob pattern can be converted to SQL LIKE.

        Simple patterns:
        - `*.py` (suffix match)
        - `**/*.py` (suffix match, equivalent to `*.py`)
        - `src/**` (prefix match)
        - `src/*.py` (prefix + suffix)

        Complex patterns (require Python filtering):
        - `src/**/test_*.py` (recursive in middle)
        - `src/[abc]/*.py` (bracket expressions)
        - `src/{a,b}/*.py` (brace expansion)

        Parameters
        ----------
        pattern : str
            Glob pattern to check.

        Returns
        -------
        bool
            True if pattern can be converted to SQL LIKE, False otherwise.
        """
        # Normalize separators
        normalized = pattern.replace("\\", "/")

        # Check for complex patterns
        if "[" in normalized or "{" in normalized:
            return False  # Bracket expressions or brace expansion

        # Check for ** in middle (not at start or end)
        if "**" in normalized:
            parts = normalized.split("**")
            expected_parts = 2  # Simple glob has at most one ** separator
            if len(parts) > expected_parts:
                return False  # Multiple ** separators
            if len(parts) == expected_parts and parts[0] and parts[1]:
                # ** in middle: e.g., "src/**/test.py"
                return False

        return True

    def get_chunk_by_id(self, chunk_id: int) -> dict | None:
        """Return a single chunk record by ID.

        Parameters
        ----------
        chunk_id : int
            Chunk identifier to retrieve from the catalog.

        Returns
        -------
        dict | None
            Chunk metadata dictionary when the ID exists, otherwise ``None``.
        """
        results = self.query_by_ids([chunk_id])
        if not results:
            return None
        return results[0]

    def get_symbols_for_chunk(self, chunk_id: int) -> list[str]:
        """Return all symbols associated with a chunk.

        Parameters
        ----------
        chunk_id : int
            Chunk ID to query symbols for.

        Returns
        -------
        list[str]
            List of symbol identifiers associated with the chunk. Returns empty
            list if chunk has no symbols or chunk_id doesn't exist.
        """
        with self.connection() as conn:
            if self._relation_exists(conn, "v_chunk_symbols"):
                sql = "SELECT symbol FROM v_chunk_symbols WHERE chunk_id = ?"
            else:
                sql = "SELECT symbol FROM chunk_symbols WHERE chunk_id = ?"
            relation = conn.execute(sql, [chunk_id])
            rows = relation.fetchall()
        return [row[0] for row in rows]

    def query_by_uri(self, uri: str, limit: int = 100) -> list[dict]:
        """Query chunks by file URI/path.

        Retrieves all chunks from a specific file. Useful for file-level operations
        like displaying all chunks in a file or filtering search results by file.

        The query uses parameterized SQL to prevent injection and efficiently
        filters by URI. Results are limited to prevent excessive memory usage
        for large files. Pass ``limit <= 0`` to disable the limit entirely
        while still preserving deterministic ordering by chunk ID.

        Parameters
        ----------
        uri : str
            File URI or path to query. Should match the uri field in the chunks
            table (typically a relative path from repo root).
        limit : int, optional
            Maximum number of chunks to return. Defaults to 100. Set higher for
            large files, but be aware of memory usage. Pass 0 or a negative value
            to disable the limit (not recommended for production).

        Returns
        -------
        list[dict]
            List of chunk records from the specified file. Each dict contains
            all chunk columns. Results are ordered by chunk ID (which typically
            corresponds to file order). Returns empty list if file not found or
            no chunks in file.

        """
        sql = "SELECT * FROM chunks WHERE uri = ? ORDER BY id"
        params: list[object] = [uri]
        if limit > 0:
            sql = "SELECT * FROM chunks WHERE uri = ? ORDER BY id LIMIT ?"
            params.append(limit)

        with self.connection() as conn:
            relation = conn.execute(sql, params)
            rows = relation.fetchall()
            cols = [desc[0] for desc in relation.description]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def get_embeddings_by_ids(self, ids: Sequence[int]) -> NDArrayF32:
        """Extract embedding vectors for given chunk IDs.

        Retrieves the pre-computed embedding vectors for chunks, typically used
        after a FAISS search to get the actual vectors for re-ranking or analysis.
        The embeddings are stored in Parquet as FixedSizeList arrays and are
        converted to NumPy arrays for efficient computation.

        The function preserves the order of input IDs in the output array. If
        an ID is not found, it's silently skipped (the output will have fewer
        rows than input IDs).

        Parameters
        ----------
        ids : Sequence[int]
            Sequence of chunk IDs to retrieve embeddings for. IDs must exist
            in the chunks table. Empty sequence returns empty array.

        Returns
        -------
        NDArrayF32
            Embedding vectors as a 2D NumPy array of shape (n_found, vec_dim)
            where n_found <= len(ids). Dtype is float32 for memory efficiency.
            Returns empty array (shape (0, vec_dim)) if no IDs provided or no
            matches found. The array is ordered by the input ID sequence.

        """
        if not ids:
            dim = self._embedding_dim()
            return np.empty((0, dim), dtype=np.float32)

        with self.connection() as conn:
            relation = conn.execute(
                """
                SELECT c.id, c.embedding, ids.position
                FROM chunks AS c
                JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                    ON c.id = ids.id
                ORDER BY ids.position
                """,
                [list(ids)],
            )
            rows = relation.fetchall()
        dim = self._embedding_dim()
        if not rows:
            return np.empty((0, dim), dtype=np.float32)

        embeddings: list[NDArrayF32] = []
        for _, embedding, _ in rows:
            if embedding is None:
                continue
            array = np.asarray(embedding, dtype=np.float32)
            if array.ndim != 1:
                continue
            embeddings.append(array)

        if not embeddings:
            return np.empty((0, dim), dtype=np.float32)

        return np.vstack(embeddings)

    def count_chunks(self) -> int:
        """Count total number of chunks in the index.

        Returns the total number of chunks across all files. Useful for monitoring
        index size and validating that indexing completed successfully.

        The count is computed efficiently using DuckDB's COUNT aggregation over
        the chunks view, which reads directly from Parquet files.

        Returns
        -------
        int
            Total number of chunks in the index. Returns 0 if the chunks view
            is empty or no Parquet files exist.

        """
        with self.connection() as conn:
            result = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return result[0] if result else 0

    def _embedding_dim(self) -> int:
        """Return the embedding dimension, caching when possible.

        Returns
        -------
        int
            Embedding dimension for the chunks table, or ``0`` when no rows exist.
        """
        if self._embedding_dim_cache is not None:
            return self._embedding_dim_cache
        with self.connection() as conn:
            result = conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
        if result and result[0] is not None:
            self._embedding_dim_cache = len(result[0])
        else:
            self._embedding_dim_cache = 0
        return self._embedding_dim_cache


__all__ = ["DuckDBCatalog"]
