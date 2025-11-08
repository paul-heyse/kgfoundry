"""DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, suppress
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Self

import duckdb
import numpy as np

from codeintel_rev.io.duckdb_manager import DuckDBManager
from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import build_histogram

if TYPE_CHECKING:
    from collections.abc import Sequence

LOGGER = get_logger(__name__)

# Prometheus metrics for scope filtering
_scope_filter_duration_seconds = build_histogram(
    "codeintel_scope_filter_duration_seconds",
    "Time to apply scope filters",
    labelnames=("filter_type",),
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
    CAST(NULL AS FLOAT[]) AS embedding
WHERE 1 = 0
"""


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
    """

    def __init__(
        self,
        db_path: Path,
        vectors_dir: Path,
        *,
        materialize: bool = False,
        manager: DuckDBManager | None = None,
    ) -> None:
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.materialize = materialize
        self.conn: duckdb.DuckDBPyConnection | None = None
        self._embedding_dim_cache: int | None = None
        self._manager = manager
        self._connection_cm: AbstractContextManager[duckdb.DuckDBPyConnection] | None = None

    def open(self) -> None:
        """Open database connection."""
        if self._manager is not None:
            self._connection_cm = self._manager.connection()
            self.conn = self._connection_cm.__enter__()
        else:
            self.conn = duckdb.connect(str(self.db_path))
        self._ensure_views()

    def close(self) -> None:
        """Close database connection."""
        if self._connection_cm is not None and self.conn is not None:
            self._connection_cm.__exit__(None, None, None)
            self._connection_cm = None
            self.conn = None
        elif self.conn:
            self.conn.close()
            self.conn = None

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

    def _ensure_views(self) -> None:
        """Create views over Parquet directories.

        Creates the `chunks` view over Parquet files and creates an index on the
        `uri` column for efficient path filtering in `query_by_filters`.

        Raises
        ------
        RuntimeError
            If the database connection has not been opened.
        """
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        parquet_pattern = str(self.vectors_dir / "**/*.parquet")
        parquet_exists = any(self.vectors_dir.rglob("*.parquet"))

        if self.materialize:
            if parquet_exists:
                self.conn.execute(
                    """
                    CREATE OR REPLACE TABLE chunks_materialized AS
                    SELECT * FROM read_parquet(?)
                    """,
                    [parquet_pattern],
                )
            else:
                self.conn.execute(
                    f"CREATE OR REPLACE TABLE chunks_materialized AS {_EMPTY_CHUNKS_SELECT}"
                )

            self.conn.execute("CREATE OR REPLACE VIEW chunks AS SELECT * FROM chunks_materialized")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_materialized_uri ON chunks_materialized(uri)"
            )
            LOGGER.info(
                "Materialized DuckDB chunks table",
                extra={
                    "materialized": True,
                    "parquet_found": parquet_exists,
                    "db_path": str(self.db_path),
                },
            )
        else:
            if parquet_exists:
                relation = self.conn.sql("SELECT * FROM read_parquet(?)", params=[parquet_pattern])
                relation.create_view("chunks", replace=True)
            else:
                self.conn.execute(f"CREATE OR REPLACE VIEW chunks AS {_EMPTY_CHUNKS_SELECT}")
            LOGGER.debug(
                "Configured DuckDB chunks view",
                extra={
                    "materialized": False,
                    "parquet_found": parquet_exists,
                    "db_path": str(self.db_path),
                },
            )

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

        Raises
        ------
        RuntimeError
            If the database connection is not open. Call open() or use the
            context manager before querying.
        """
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        if not ids:
            return []

        relation = self.conn.execute(
            """
            SELECT c.*
            FROM chunks AS c
            JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                ON c.id = ids.id
            ORDER BY ids.position
            """,
            [list(ids)],
        )
        rows = relation.fetchall()
        cols = [desc[0] for desc in relation.description]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def query_by_filters(  # noqa: C901, PLR0912, PLR0915, PLR0914 - complex filtering logic with SQL generation and post-processing
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

        Raises
        ------
        RuntimeError
            If the database connection is not open. Call open() or use the
            context manager before querying.

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
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        if not ids:
            return []

        # Measure filtering duration
        start_time = perf_counter()

        # Import LANGUAGE_EXTENSIONS here to avoid circular dependency
        from codeintel_rev.mcp_server.scope_utils import (  # noqa: PLC0415 - import inside function to avoid circular dependency
            LANGUAGE_EXTENSIONS,
            path_matches_glob,
        )

        # Build base query with ID filtering
        query_parts = [
            "SELECT c.*",
            "FROM chunks AS c",
            "JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)",
            "  ON c.id = ids.id",
        ]
        params: list[object] = [list(ids)]
        where_clauses: list[str] = []

        # Convert simple globs to SQL LIKE patterns
        simple_include_patterns: list[str] = []
        complex_include_patterns: list[str] = []
        simple_exclude_patterns: list[str] = []
        complex_exclude_patterns: list[str] = []

        if include_globs:
            for pattern in include_globs:
                if self._is_simple_glob(pattern):
                    sql_pattern = self._glob_to_sql_like(pattern)
                    simple_include_patterns.append(sql_pattern)
                else:
                    complex_include_patterns.append(pattern)

        if exclude_globs:
            for pattern in exclude_globs:
                if self._is_simple_glob(pattern):
                    sql_pattern = self._glob_to_sql_like(pattern)
                    simple_exclude_patterns.append(sql_pattern)
                else:
                    complex_exclude_patterns.append(pattern)

        # Add SQL WHERE clauses for simple patterns
        if simple_include_patterns:
            like_clauses = " OR ".join("c.uri LIKE ? ESCAPE '\\'" for _ in simple_include_patterns)
            where_clauses.append(f"({like_clauses})")
            params.extend(simple_include_patterns)

        if simple_exclude_patterns:
            for pattern in simple_exclude_patterns:
                where_clauses.append("c.uri NOT LIKE ? ESCAPE '\\'")
                params.append(pattern)

        # Add language filter (SQL LIKE for extensions)
        if languages:
            extensions: set[str] = set()
            for lang in languages:
                lang_extensions = LANGUAGE_EXTENSIONS.get(lang.lower(), [])
                extensions.update(lang_extensions)

            if extensions:
                ext_clauses = " OR ".join("c.uri LIKE ? ESCAPE '\\'" for _ in extensions)
                where_clauses.append(f"({ext_clauses})")
                params.extend(f"%{DuckDBCatalog._escape_like_wildcards(ext)}" for ext in extensions)
            else:
                # No extensions found for requested languages -> no matches
                # Return empty by adding impossible WHERE clause
                where_clauses.append("1 = 0")

        # Build final query
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        query_parts.append("ORDER BY ids.position")

        query = "\n".join(query_parts)

        # Execute SQL query
        relation = self.conn.execute(query, params)
        rows = relation.fetchall()
        cols = [desc[0] for desc in relation.description]
        results = [dict(zip(cols, row, strict=True)) for row in rows]

        # Post-filter complex globs using Python fnmatch
        if complex_include_patterns or complex_exclude_patterns:
            filtered_results: list[dict] = []
            for chunk in results:
                uri = chunk.get("uri", "")
                if not isinstance(uri, str):
                    continue

                # Check complex include patterns
                if complex_include_patterns and not any(
                    path_matches_glob(uri, pattern) for pattern in complex_include_patterns
                ):
                    continue  # Doesn't match any include pattern

                # Check complex exclude patterns
                if complex_exclude_patterns and any(
                    path_matches_glob(uri, pattern) for pattern in complex_exclude_patterns
                ):
                    continue  # Matches an exclude pattern

                filtered_results.append(chunk)
            results = filtered_results

        # Record filtering duration
        duration = perf_counter() - start_time
        filter_type = "none"
        if include_globs or exclude_globs:
            filter_type = "combined" if languages else "glob"
        elif languages:
            filter_type = "language"
        # Record metric (may fail in test environments without Prometheus registry)
        with suppress(ValueError):
            _scope_filter_duration_seconds.labels(filter_type=filter_type).observe(duration)

        return results

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

    @staticmethod
    def _glob_to_sql_like(pattern: str) -> str:
        """Convert simple glob pattern to SQL LIKE pattern.

        Conversions:
        - `*.py` → `%.py`
        - `**/*.py` → `%.py` (same as `*.py`)
        - `src/**` → `src/%`
        - `src/*.py` → `src/%.py`

        Parameters
        ----------
        pattern : str
            Simple glob pattern (must pass `_is_simple_glob` check).

        Returns
        -------
        str
            SQL LIKE pattern ready for parameterized query.
        """
        # Normalize separators
        normalized = pattern.replace("\\", "/")

        starts_with_recursive = normalized.startswith("**/")
        recursive_remainder = normalized[len("**/") :] if starts_with_recursive else ""

        escaped = DuckDBCatalog._escape_like_wildcards(normalized)

        # Replace ** with % (matches any characters including slashes)
        escaped = escaped.replace("**", "%")

        # Replace * with % (matches any characters)
        escaped = escaped.replace("*", "%")

        # Replace ? with _ (matches single character)
        escaped = escaped.replace("?", "_")

        if (
            starts_with_recursive
            and recursive_remainder.startswith("*")
            and escaped.startswith("%/")
        ):
            escaped = escaped.replace("/%", "%", 1)
            escaped = "%" + escaped.lstrip("%")

        return escaped

    @staticmethod
    def _escape_like_wildcards(pattern: str) -> str:
        """Escape literal SQL LIKE wildcards using backslash.

        Parameters
        ----------
        pattern : str
            Pattern string to escape.

        Returns
        -------
        str
            Escaped pattern string.
        """
        return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

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

        Raises
        ------
        RuntimeError
            If the database connection is not open. Call open() or use the
            context manager before querying.
        """
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        sql = "SELECT * FROM chunks WHERE uri = ? ORDER BY id"
        params: list[object] = [uri]
        if limit > 0:
            sql = "SELECT * FROM chunks WHERE uri = ? ORDER BY id LIMIT ?"
            params.append(limit)

        relation = self.conn.execute(sql, params)
        rows = relation.fetchall()
        cols = [desc[0] for desc in relation.description]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def get_embeddings_by_ids(self, ids: Sequence[int]) -> np.ndarray:
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
        np.ndarray
            Embedding vectors as a 2D NumPy array of shape (n_found, vec_dim)
            where n_found <= len(ids). Dtype is float32 for memory efficiency.
            Returns empty array (shape (0, vec_dim)) if no IDs provided or no
            matches found. The array is ordered by the input ID sequence.

        Raises
        ------
        RuntimeError
            If the database connection is not open. Call open() or use the
            context manager before querying.
        """
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        if not ids:
            dim = self._embedding_dim()
            return np.empty((0, dim), dtype=np.float32)

        relation = self.conn.execute(
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

        embeddings: list[np.ndarray] = []
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

        Raises
        ------
        RuntimeError
            If the database connection is not open. Call open() or use the
            context manager before querying.
        """
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)

        result = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return result[0] if result else 0

    def _embedding_dim(self) -> int:
        """Return the embedding dimension, caching when possible.

        Returns
        -------
        int
            Embedding dimension for the chunks table, or ``0`` when no rows exist.

        Raises
        ------
        RuntimeError
            If the database connection has not been opened.
        """
        if self._embedding_dim_cache is not None:
            return self._embedding_dim_cache
        if not self.conn:
            msg = "Connection not open"
            raise RuntimeError(msg)
        result = self.conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
        if result and result[0] is not None:
            self._embedding_dim_cache = len(result[0])
        else:
            self._embedding_dim_cache = 0
        return self._embedding_dim_cache


__all__ = ["DuckDBCatalog"]
