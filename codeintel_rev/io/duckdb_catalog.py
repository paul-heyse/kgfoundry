"""DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
"""

# ruff: noqa: SLF001

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypedDict, Unpack, cast

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
from codeintel_rev.observability.otel import record_span_event
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.observability.timeline import current_timeline
from codeintel_rev.telemetry.decorators import span_context
from codeintel_rev.telemetry.otel_metrics import build_histogram
from codeintel_rev.telemetry.steps import StepEvent, emit_step
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    import duckdb
    import numpy as np
else:
    duckdb = cast("duckdb", LazyModule("duckdb", "DuckDB catalog operations"))
    np = cast("np", LazyModule("numpy", "DuckDB catalog embeddings"))

LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class IdMapMeta:
    """Metadata describing a materialized FAISS ID map join."""

    parquet_path: str
    parquet_hash: str
    row_count: int
    refreshed: bool


def _log_extra(**kwargs: object) -> dict[str, object]:
    """Return structured log extras for catalog events.

    This function creates a structured logging payload by combining a component
    identifier ("duckdb_catalog") with additional keyword arguments. The function
    is used to create consistent log context for DuckDB catalog operations.

    Parameters
    ----------
    **kwargs : object
        Additional keyword arguments to include in the logging payload. All arguments
        are merged into the returned dictionary with the component identifier.
        Values must be JSON-serializable for structured logging.

    Returns
    -------
    dict[str, object]
        Structured logging payload dictionary containing "component": "duckdb_catalog"
        and all provided keyword arguments. The dictionary is suitable for use with
        Python's logging module's extra parameter.
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
_hydration_duration_seconds = build_histogram(
    "codeintel_duckdb_hydration_seconds",
    "Time to hydrate chunks or embeddings by id",
    labelnames=("op",),
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

_CST_KIND_QUERIES: dict[str, str] = {
    "uri": """
        SELECT DISTINCT kind
        FROM cst_nodes
        WHERE uri = ?
          AND COALESCE(end_line, start_line) >= ?
          AND COALESCE(start_line, end_line) <= ?
        """,
    "path": """
        SELECT DISTINCT kind
        FROM cst_nodes
        WHERE path = ?
          AND COALESCE(end_line, start_line) >= ?
          AND COALESCE(start_line, end_line) <= ?
        """,
}


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


@dataclass(slots=True, frozen=True)
class StructureAnnotations:
    """Structure-aware metadata joined onto explainability pools."""

    uri: str
    symbol_hits: tuple[str, ...]
    ast_node_kinds: tuple[str, ...]
    cst_matches: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class DuckDBCatalogOptions:
    """Optional configuration bundle for DuckDB catalog instantiation."""

    materialize: bool = False
    manager: DuckDBManager | None = None
    log_queries: bool | None = None
    repo_root: Path | None = None


class _DuckDBQueryMixin:
    """Chunk-level query helpers shared by :class:`DuckDBCatalog`."""

    def query_by_ids(self, ids: Sequence[int]) -> list[dict]:
        """Query chunks by their unique IDs.

        This method retrieves chunk records from the DuckDB catalog for the
        specified chunk identifiers. It performs a SQL query to fetch chunk
        metadata (URI, start/end lines, symbols, etc.) and returns the results
        as a list of dictionaries. The method handles empty input gracefully
        and records telemetry for observability.

        Parameters
        ----------
        ids : Sequence[int]
            Sequence of chunk identifiers to query. Empty sequences return an
            empty list. Duplicate IDs may result in duplicate records depending
            on database constraints.

        Returns
        -------
        list[dict]
            List of chunk record dictionaries, each containing chunk metadata
            fields (e.g., id, uri, start_line, end_line, symbols). The list
            may be shorter than the input if some IDs don't exist in the catalog.
            Empty list when no IDs are provided or no matching chunks are found.
            Records are ordered to match the input ID sequence when possible.
        """
        if not ids:
            return []

        catalog = cast("DuckDBCatalog", self)
        timeline = current_timeline()
        span_attrs = {"op": "query_by_ids", "asked_for": len(ids)}
        start_time = None
        if timeline is not None:
            start_time = perf_counter()
            timeline.event(
                "duckdb.hydrate.start",
                "catalog",
                attrs=span_attrs,
            )

        sql = """
            SELECT c.*
            FROM chunks AS c
            JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                ON c.id = ids.id
            ORDER BY ids.position
            """
        params = [list(ids)]
        otel_attrs = {
            Attrs.COMPONENT: "duckdb",
            Attrs.REQUEST_STAGE: "hydrate",
            Attrs.DUCKDB_SQL_BYTES: len(sql.encode("utf-8")),
        }
        perf_start = perf_counter()
        span_cm = span_context(
            "catalog.hydrate",
            stage="catalog.hydrate",
            attrs=otel_attrs,
            emit_checkpoint=True,
        )
        with span_cm as (span, _):
            with catalog._readonly_connection() as conn:
                catalog._log_query(sql, params)
                relation = conn.execute(sql, params)
                rows = relation.fetchall()
                cols = [desc[0] for desc in relation.description]
            payload = [dict(zip(cols, row, strict=True)) for row in rows]
        if span is not None:
            with suppress(AttributeError):  # pragma: no cover - noop span
                span.set_attribute(Attrs.DUCKDB_ROWS, len(payload))
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
        _hydration_duration_seconds.labels(op="chunks_by_ids").observe(
            max(perf_counter() - perf_start, 0.0)
        )
        emit_step(
            StepEvent(
                kind="duckdb.query",
                status="completed",
                payload={
                    "op": "chunks_by_ids",
                    "returned": len(payload),
                    "requested": len(ids),
                },
            )
        )
        return payload

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, StructureAnnotations]:
        """Return structural overlays (symbols/AST/CST) for chunk ``ids``.

        Parameters
        ----------
        ids : Sequence[int]
            Chunk identifiers to hydrate with structural metadata.

        Returns
        -------
        dict[int, StructureAnnotations]
            Mapping of chunk ID to :class:`StructureAnnotations` describing URI,
            symbol hits, AST node kinds, and CST matches.
        """
        cleaned = [int(chunk_id) for chunk_id in ids if chunk_id is not None]
        if not cleaned:
            return {}
        unique_ids = list(dict.fromkeys(cleaned))
        catalog = cast("DuckDBCatalog", self)
        with catalog._readonly_connection() as conn:
            base_rows = self._fetch_annotation_rows(conn, unique_ids)
            annotations, boundaries = self._initialize_annotation_maps(base_rows)
            if not annotations:
                return {}
            if _relation_exists(conn, "chunk_symbols"):
                self._attach_chunk_symbols(conn, unique_ids, annotations)
            if _relation_exists(conn, "ast_nodes"):
                self._attach_ast_nodes(conn, boundaries, annotations)
            if _relation_exists(conn, "cst_nodes"):
                path_column = self._resolve_cst_path_column(conn)
                self._attach_cst_nodes(conn, path_column, boundaries, annotations)
        return self._coerce_annotation_payload(unique_ids, annotations)

    @staticmethod
    def _fetch_annotation_rows(
        conn: duckdb.DuckDBPyConnection,
        unique_ids: Sequence[int],
    ) -> list[tuple[int, str, int | None, int | None, Sequence[str] | None]]:
        return conn.execute(
            """
            SELECT
                id,
                uri,
                start_line,
                end_line,
                COALESCE(symbols, []::VARCHAR[]) AS symbols
            FROM chunks
            WHERE id IN (SELECT * FROM UNNEST(?))
            """,
            [list(unique_ids)],
        ).fetchall()

    @staticmethod
    def _initialize_annotation_maps(
        rows: Sequence[tuple[int, str, int | None, int | None, Sequence[str] | None]],
    ) -> tuple[dict[int, dict[str, object]], dict[int, tuple[int, int]]]:
        annotations: dict[int, dict[str, object]] = {}
        boundaries: dict[int, tuple[int, int]] = {}
        for chunk_id, uri, start_line, end_line, symbols in rows:
            annotations[int(chunk_id)] = {
                "uri": uri,
                "symbol_hits": tuple(symbols or ()),
                "ast_node_kinds": (),
                "cst_matches": (),
            }
            boundaries[int(chunk_id)] = (int(start_line or 0), int(end_line or 0))
        return annotations, boundaries

    @staticmethod
    def _attach_chunk_symbols(
        conn: duckdb.DuckDBPyConnection,
        unique_ids: Sequence[int],
        annotations: dict[int, dict[str, object]],
    ) -> None:
        rows = conn.execute(
            """
            SELECT chunk_id, array_agg(DISTINCT symbol ORDER BY symbol) AS symbols
            FROM chunk_symbols
            WHERE chunk_id IN (SELECT * FROM UNNEST(?))
            GROUP BY chunk_id
            """,
            [list(unique_ids)],
        ).fetchall()
        for chunk_id, symbols in rows:
            payload = annotations.get(int(chunk_id))
            if payload is not None:
                payload["symbol_hits"] = tuple(symbols or ())

    @staticmethod
    def _attach_ast_nodes(
        conn: duckdb.DuckDBPyConnection,
        boundaries: Mapping[int, tuple[int, int]],
        annotations: dict[int, dict[str, object]],
    ) -> None:
        for chunk_id, (start_line, end_line) in boundaries.items():
            payload = annotations.get(chunk_id)
            if payload is None:
                continue
            rows = conn.execute(
                """
                SELECT DISTINCT node_type
                FROM ast_nodes
                WHERE path = ?
                  AND COALESCE(end_lineno, lineno) >= ?
                  AND COALESCE(lineno, end_lineno) <= ?
                """,
                [payload["uri"], start_line, end_line],
            ).fetchall()
            if rows:
                payload["ast_node_kinds"] = tuple(dict.fromkeys(row[0] for row in rows if row[0]))

    @staticmethod
    def _resolve_cst_path_column(conn: duckdb.DuckDBPyConnection) -> str:
        for column, probe_sql in (
            ("uri", "SELECT uri FROM cst_nodes LIMIT 0"),
            ("path", "SELECT path FROM cst_nodes LIMIT 0"),
        ):
            try:
                conn.execute(probe_sql)
            except duckdb.Error:
                continue
            else:
                return column
        return "uri"

    @staticmethod
    def _attach_cst_nodes(
        conn: duckdb.DuckDBPyConnection,
        path_column: str,
        boundaries: Mapping[int, tuple[int, int]],
        annotations: dict[int, dict[str, object]],
    ) -> None:
        sql = _CST_KIND_QUERIES.get(path_column)
        if sql is None:
            return
        try:
            for chunk_id, (start_line, end_line) in boundaries.items():
                payload = annotations.get(chunk_id)
                if payload is None:
                    continue
                rows = conn.execute(sql, [payload["uri"], start_line, end_line]).fetchall()
                if rows:
                    payload["cst_matches"] = tuple(
                        dict.fromkeys(row[0] for row in rows if row[0]),
                    )
        except duckdb.Error as exc:  # pragma: no cover - schema may evolve
            LOGGER.debug(
                "Skipping CST annotations",
                extra=_log_extra(error=str(exc)),
            )

    @staticmethod
    def _coerce_annotation_payload(
        ordered_ids: Sequence[int],
        annotations: Mapping[int, dict[str, object]],
    ) -> dict[int, StructureAnnotations]:
        result: dict[int, StructureAnnotations] = {}
        for chunk_id in ordered_ids:
            payload = annotations.get(chunk_id)
            if payload is None:
                continue
            symbol_hits = tuple(cast("Sequence[str]", payload["symbol_hits"]))
            ast_node_kinds = tuple(cast("Sequence[str]", payload["ast_node_kinds"]))
            cst_matches = tuple(cast("Sequence[str]", payload["cst_matches"]))
            result[chunk_id] = StructureAnnotations(
                uri=str(payload["uri"]),
                symbol_hits=symbol_hits,
                ast_node_kinds=ast_node_kinds,
                cst_matches=cst_matches,
            )
        return result


class _LegacyOptions(TypedDict, total=False):
    materialize: bool
    manager: DuckDBManager | None
    log_queries: bool
    repo_root: Path


class DuckDBCatalog(_DuckDBQueryMixin):
    """DuckDB catalog for querying chunks.

    This class provides a high-level interface for querying chunk metadata and
    embeddings stored in DuckDB. The catalog can operate in two modes: view-based
    (zero-copy queries from Parquet files) or materialized (persisted tables with
    indexes). The catalog manages DuckDB connections, builds query views, and
    provides methods for fetching embeddings and metadata by IDs.

    Attributes
    ----------
    relation_exists : ClassVar[Callable[[duckdb.DuckDBPyConnection, str], bool]]
        Class variable referencing the module-level ``relation_exists()`` function.
        Used to check if a table or view exists in the DuckDB catalog. Accepts a
        DuckDB connection and relation name, returns ``True`` if the relation exists.

    Parameters
    ----------
    db_path : Path
        Path to the DuckDB database file. The database is created if it doesn't
        exist. Used for storing catalog metadata and materialized tables when
        materialize is True.
    vectors_dir : Path
        Directory containing Parquet files with chunk embeddings and metadata.
        The catalog reads from this directory to build views or materialize tables.
        The directory structure is expected to match the standard layout.
    options : DuckDBCatalogOptions | None, optional
        Configuration options dataclass containing materialize, manager, log_queries,
        and repo_root settings. When None, uses default options. Cannot be mixed
        with legacy_kwargs. Defaults to None.
    **legacy_kwargs : Unpack[_LegacyOptions]
        Legacy keyword arguments for backward compatibility. Supported keys:
        materialize (bool), manager (DuckDBManager | None), log_queries (bool),
        repo_root (Path). Cannot be used when options is provided. Raises TypeError
        for unknown keys. The type is Unpack[_LegacyOptions] where _LegacyOptions
        is a TypedDict defining the allowed keyword arguments.

    Raises
    ------
    ValueError
        Raised when both options and legacy_kwargs are provided (mixing is not allowed).
    TypeError
        Raised when legacy_kwargs contains unsupported keyword arguments.
    """

    relation_exists: ClassVar[Callable[[duckdb.DuckDBPyConnection, str], bool]]

    def __init__(
        self,
        db_path: Path,
        vectors_dir: Path,
        *,
        options: DuckDBCatalogOptions | None = None,
        **legacy_kwargs: Unpack[_LegacyOptions],
    ) -> None:
        if options is not None and legacy_kwargs:
            msg = "Cannot mix DuckDBCatalog options dataclass with keyword overrides."
            raise ValueError(msg)
        if options is None:
            if legacy_kwargs:
                allowed = {"materialize", "manager", "log_queries", "repo_root"}
                unknown = set(legacy_kwargs) - allowed
                if unknown:
                    msg = f"Unsupported DuckDBCatalog keyword(s): {', '.join(sorted(unknown))}"
                    raise TypeError(msg)
                options = DuckDBCatalogOptions(**legacy_kwargs)
            else:
                options = DuckDBCatalogOptions()
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.materialize = options.materialize
        manager = options.manager or DuckDBManager(db_path)
        self._manager = manager
        self._query_builder = DuckDBQueryBuilder()
        self._embedding_dim_cache: int | None = None
        self._init_lock = Lock()
        self._views_ready = False
        self._log_queries = (
            options.log_queries if options.log_queries is not None else manager.config.log_queries
        )
        self._data_root = vectors_dir.parent.resolve()
        repo_root = options.repo_root
        self._repo_root = repo_root.resolve() if repo_root is not None else self._data_root.parent
        default_idmap = (self._data_root / "faiss/faiss_idmap.parquet").resolve()
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

    @contextmanager
    def _readonly_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a read-only DuckDB connection for hydration queries.

        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection opened in read-only mode for catalog reads.
        """
        self._ensure_ready()
        with self._manager.readonly_connection() as conn:
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
        chunks_ready = _relation_exists(conn, "chunks")
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
        modules_installed = self._install_parquet_view(
            conn, "modules", self._data_root / "modules/modules.parquet"
        )
        if not modules_installed:
            modules_json = self._repo_root / "build/enrich/modules/modules.jsonl"
            self._install_json_view(conn, "modules", modules_json)
        self._install_parquet_view(
            conn,
            "scip_occurrences",
            self._data_root / "scip/scip_occurrences.parquet",
        )
        self._install_parquet_view(conn, "ast_nodes", self._data_root / "ast/ast_nodes.parquet")
        self._install_parquet_view(conn, "cst_nodes", self._data_root / "cst/cst_nodes.parquet")
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

    def _install_json_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
        source: Path,
    ) -> bool:
        if not source.exists():
            return False
        sql = "SELECT * FROM read_json_auto(?)"
        params = [str(source)]
        self._log_query(sql, params)
        relation = conn.sql(sql, params=params)
        relation.create_view(view_name, replace=True)
        LOGGER.info(
            "Configured DuckDB JSON view",
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
                parquet_path TEXT,
                parquet_hash TEXT,
                checksum     TEXT,
                row_count    BIGINT NOT NULL,
                updated_at   TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute("ALTER TABLE faiss_idmap_mat_meta ADD COLUMN IF NOT EXISTS parquet_path TEXT")
        conn.execute("ALTER TABLE faiss_idmap_mat_meta ADD COLUMN IF NOT EXISTS parquet_hash TEXT")
        conn.execute("ALTER TABLE faiss_idmap_mat_meta ADD COLUMN IF NOT EXISTS checksum TEXT")

    @staticmethod
    def _ensure_faiss_join_view(conn: duckdb.DuckDBPyConnection) -> None:
        """Expose chunks joined with FAISS ID map for deterministic hydration."""
        conn.execute(
            """
            CREATE OR REPLACE VIEW v_faiss_join AS
            SELECT
                c.*,
                f.faiss_row
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
            params = [str(path)]
            self._log_query("SELECT faiss_row, external_id FROM read_parquet(?)", params)
            relation = conn.sql("SELECT faiss_row, external_id FROM read_parquet(?)", params=params)
            relation.create_view("faiss_idmap", replace=True)
            LOGGER.info(
                "Configured DuckDB view",
                extra=_log_extra(view="faiss_idmap", source=str(path)),
            )
            return

        if _relation_exists(conn, "faiss_idmap_mat"):
            conn.execute(
                """
                CREATE OR REPLACE VIEW faiss_idmap AS
                SELECT
                    faiss_row,
                    external_id
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
                CAST(NULL AS BIGINT) AS external_id
            WHERE 1 = 0
            """
        )

    def ensure_faiss_idmap_views(self, idmap_path: Path | None = None) -> None:
        """Install/refresh FAISS id map views from a specific Parquet file."""
        with self.connection() as conn:
            self._ensure_faiss_idmap_view(conn, idmap_path)
            self._ensure_faiss_join_view(conn)

    def materialize_faiss_join(self) -> None:
        """Persist ``v_faiss_join`` into ``faiss_join_mat`` for BI workloads."""
        with self.connection() as conn:
            if not _relation_exists(conn, "v_faiss_join"):
                return
            sql = "CREATE OR REPLACE TABLE faiss_join_mat AS SELECT * FROM v_faiss_join"
            self._log_query(sql, None)
            conn.execute(sql)
            row = conn.execute("SELECT COUNT(*) FROM faiss_join_mat").fetchone()
            rows = int(row[0]) if row and row[0] is not None else 0
            LOGGER.info(
                "Materialized FAISS join table",
                extra=_log_extra(rows=rows, table="faiss_join_mat"),
            )

    def set_idmap_path(self, path: Path) -> None:
        """Override the FAISS id map path used for view installation."""
        self._idmap_path = path.resolve()

    def register_idmap_parquet(self, path: Path, *, materialize: bool = False) -> dict[str, Any]:
        """Register a FAISS id map Parquet file and refresh views/materialized joins.

        Parameters
        ----------
        path : Path
            Path to the Parquet file containing the FAISS ID map. The path is
            expanded (resolving ~) and resolved to an absolute path before use.
        materialize : bool, optional
            If True, materializes the FAISS join table instead of creating views
            (default: False). Materialization improves query performance but
            requires more storage and must be refreshed when the ID map changes.

        Returns
        -------
        dict[str, Any]
            Statistics dictionary from refresh_faiss_idmap_mat_if_changed(),
            containing information about the materialized table refresh operation
            (e.g., row counts, refresh status). The dictionary includes keys
            such as "rows", "checksum", and "refreshed" indicating the state
            of the materialized table.
        """
        resolved = path.expanduser().resolve()
        self.set_idmap_path(resolved)
        stats = self.refresh_faiss_idmap_mat_if_changed(resolved)
        if materialize:
            self.materialize_faiss_join()
        else:
            self.ensure_faiss_idmap_views(resolved)
        return stats

    def ensure_pool_views(self, pool_path: Path) -> None:
        """Expose the latest evaluator pool and coverage join as DuckDB views."""
        with self.connection() as conn:
            sql = "SELECT * FROM read_parquet(?)"
            params = [str(pool_path)]
            self._log_query(sql, params)
            relation = conn.sql(sql, params=params)
            relation.create_view("v_faiss_pool", replace=True)
            LOGGER.info(
                "Configured DuckDB view",
                extra=_log_extra(view="v_faiss_pool", source=str(pool_path)),
            )
            try:
                conn.execute(
                    """
                    CREATE OR REPLACE VIEW v_pool_coverage AS
                    SELECT
                        pool.*,
                        chunks.lang,
                        modules.repo_path AS repo_path,
                        modules.module_name,
                        modules.tags
                    FROM v_faiss_pool AS pool
                    LEFT JOIN chunks ON chunks.id = pool.chunk_id
                    LEFT JOIN modules ON modules.repo_path = pool.uri
                    """
                )
            except duckdb.Error:
                conn.execute(
                    """
                    CREATE OR REPLACE VIEW v_pool_coverage AS
                    SELECT
                        pool.*,
                        chunks.lang
                    FROM v_faiss_pool AS pool
                    LEFT JOIN chunks ON chunks.id = pool.chunk_id
                    """
                )
            LOGGER.info(
                "Configured DuckDB view",
                extra=_log_extra(view="v_pool_coverage", source=str(pool_path)),
            )

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
        stats: dict[str, Any]
        with self._manager.connection() as conn:
            self._ensure_views(conn)
            meta = refresh_faiss_idmap_materialized(
                conn,
                idmap_parquet=str(idmap_parquet),
                chunks_parquet=str(self.vectors_dir / "**/*.parquet"),
            )
            stats = {
                "refreshed": meta.refreshed,
                "checksum": meta.parquet_hash,
                "rows": meta.row_count,
            }
        LOGGER.info(
            "faiss_idmap_materialized",
            extra=_log_extra(rows=stats["rows"], checksum=stats["checksum"]),
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
        list[tuple[int, np.ndarray]]
            Chunk identifiers paired with embedding vectors. Each tuple contains
            a chunk ID (int) and its corresponding embedding vector as a NumPy
            array (np.ndarray).
        """
        if limit <= 0:
            return []
        with self._readonly_connection() as conn:
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

        span_attrs = {
            Attrs.COMPONENT: "duckdb",
            Attrs.REQUEST_STAGE: "hydrate",
            "filters.include": bool(include_globs),
            "filters.exclude": bool(exclude_globs),
            "filters.languages": bool(languages),
            Attrs.DUCKDB_SQL_BYTES: 0,
        }
        perf_start = perf_counter()
        results: list[dict] = []
        with span_context(
            "catalog.hydrate",
            stage="catalog.hydrate",
            attrs=span_attrs,
            emit_checkpoint=True,
        ) as (span, _):
            start_time = perf_counter()
            spec = self._build_scope_filter_spec(
                ids,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                languages=languages,
            )

            if languages and not spec.language_extensions:
                self._observe_scope_filter_duration(
                    start_time, include_globs, exclude_globs, languages
                )
            else:
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
                span_attrs[Attrs.DUCKDB_SQL_BYTES] = len(sql.encode("utf-8"))

                with self._readonly_connection() as conn:
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

                self._observe_scope_filter_duration(
                    start_time, include_globs, exclude_globs, languages
                )

            if span is not None and span.is_recording():
                with suppress(AttributeError):
                    span.set_attribute(
                        Attrs.DUCKDB_SQL_BYTES, int(span_attrs[Attrs.DUCKDB_SQL_BYTES])
                    )
                    span.set_attribute(Attrs.DUCKDB_ROWS, len(results))

        duration = max(perf_counter() - perf_start, 0.0)
        _hydration_duration_seconds.labels(op="chunks_by_filters").observe(duration)
        self._log_scope_filter_results(
            include_globs,
            exclude_globs,
            languages,
            results,
            timeline=current_timeline(),
            requested=len(ids),
            duration=duration,
        )
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
        with self._readonly_connection() as conn:
            if _relation_exists(conn, "v_chunk_symbols"):
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

        timeline = current_timeline()
        attrs = {"uri": uri, "limit": limit}
        with (
            span_context(
                "duckdb.query_by_uri",
                stage="catalog.query",
                attrs=attrs,
            ),
            self._readonly_connection() as conn,
        ):
            relation = conn.execute(sql, params)
            rows = relation.fetchall()
            cols = [desc[0] for desc in relation.description]
        payload = [dict(zip(cols, row, strict=True)) for row in rows]
        limited = bool(limit > 0 and len(payload) >= limit)
        record_span_event(
            "duckdb.query_by_uri.result",
            uri=uri,
            rows=len(payload),
            limited=limited,
        )
        if limited and timeline is not None:
            timeline.event(
                "duckdb.query.limit",
                "duckdb",
                attrs={"uri": uri, "limit": limit, "rows": len(payload)},
            )
        return payload

    def get_embeddings_by_ids(self, ids: Sequence[int]) -> tuple[list[int], NDArrayF32]:
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
        tuple[list[int], NDArrayF32]
            Tuple of (resolved_ids, vectors) ordered by the input ID sequence.
            ``resolved_ids`` contains the chunk IDs that were found. The vectors
            array has shape ``(len(resolved_ids), vec_dim)`` and dtype float32.

        """
        requested_ids = [int(chunk_id) for chunk_id in ids]
        if not requested_ids:
            dim = self._embedding_dim()
            return [], np.empty((0, dim), dtype=np.float32)

        attrs = {"requested": len(requested_ids)}
        perf_start = perf_counter()
        timeline = current_timeline()
        with (
            span_context(
                "duckdb.get_embeddings_by_ids",
                stage="catalog.hydrate",
                attrs=attrs,
            ),
            self.connection() as conn,
        ):
            relation = conn.execute(
                """
                SELECT c.id, c.embedding, ids.position
                FROM chunks AS c
                JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                    ON c.id = ids.id
                ORDER BY ids.position
                """,
                [requested_ids],
            )
            rows = relation.fetchall()
        dim = self._embedding_dim()
        if not rows:
            return [], np.empty((0, dim), dtype=np.float32)

        ordered_ids: list[int] = []
        embeddings: list[NDArrayF32] = []
        for chunk_id, embedding, _ in rows:
            if chunk_id is None or embedding is None:
                continue
            array = np.asarray(embedding, dtype=np.float32)
            if array.ndim != 1:
                continue
            ordered_ids.append(int(chunk_id))
            embeddings.append(array)

        if not embeddings:
            return [], np.empty((0, dim), dtype=np.float32)

        vectors = np.vstack(embeddings)
        record_span_event(
            "duckdb.get_embeddings_by_ids.result",
            requested=len(requested_ids),
            returned=len(ordered_ids),
        )
        if timeline is not None:
            timeline.event(
                "duckdb.embeddings",
                "duckdb",
                attrs={"requested": len(requested_ids), "returned": len(ordered_ids)},
            )
        _hydration_duration_seconds.labels(op="embeddings_by_ids").observe(
            max(perf_counter() - perf_start, 0.0)
        )
        return ordered_ids, vectors

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
        with self._readonly_connection() as conn:
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
        with self._readonly_connection() as conn:
            result = conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
        if result and result[0] is not None:
            self._embedding_dim_cache = len(result[0])
        else:
            self._embedding_dim_cache = 0
        return self._embedding_dim_cache


def _relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Return True when a table or view with ``name`` exists in the main schema.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Active DuckDB connection to query.
    name : str
        Name of the table or view to check for existence.

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


def relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Public helper returning True when a DuckDB relation exists.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Active DuckDB connection to query.
    name : str
        Name of the table or view to check for existence.

    Returns
    -------
    bool
        ``True`` when the relation exists, otherwise ``False``.
    """
    return _relation_exists(conn, name)


def _file_checksum(path: Path) -> str:
    """Return SHA-256 checksum for ``path``.

    Parameters
    ----------
    path : Path
        File path to compute checksum for.

    Returns
    -------
    str
        Hex digest string representing the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parquet_hash(path: str | Path) -> str:
    """Return SHA256 checksum for the Parquet file at ``path``.

    This function computes a SHA256 hash of a Parquet file's contents for
    integrity verification. It is used by catalog operations to detect changes
    in FAISS ID map or chunk metadata files, enabling cache invalidation when
    data files are updated.

    Parameters
    ----------
    path : str | Path
        Path to the Parquet file to hash.

    Returns
    -------
    str
        Hexadecimal SHA256 digest representing the Parquet file contents.
    """
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def ensure_faiss_idmap_view(
    conn: duckdb.DuckDBPyConnection,
    *,
    idmap_parquet: str,
    chunks_parquet: str,
) -> None:
    """Register ``v_faiss_join`` by joining FAISS ID map and chunk metadata."""
    conn.sql("SELECT * FROM read_parquet(?)", params=[idmap_parquet]).create_view(
        "v_faiss_idmap", replace=True
    )
    conn.sql("SELECT * FROM read_parquet(?)", params=[chunks_parquet]).create_view(
        "v_chunks", replace=True
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_faiss_join AS
        SELECT
            idmap.faiss_row,
            idmap.external_id AS chunk_id,
            chunks.uri,
            chunks.start_line,
            chunks.end_line,
            chunks.language,
            chunks.text
        FROM v_faiss_idmap AS idmap
        LEFT JOIN v_chunks AS chunks
          ON chunks.id = idmap.external_id
        """
    )


def refresh_faiss_idmap_materialized(
    conn: duckdb.DuckDBPyConnection,
    *,
    idmap_parquet: str,
    chunks_parquet: str,
) -> IdMapMeta:
    """Materialize ``v_faiss_join`` into ``faiss_idmap_mat`` with checksum guard.

    This function refreshes the materialized FAISS ID map table by computing checksums
    of the source Parquet files and comparing them to cached values. If the checksums
    differ, the materialized table is rebuilt from the view. Used by catalog
    operations to ensure ID map queries remain fast while staying synchronized with
    updated index files.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    idmap_parquet : str
        Path to the FAISS ID map Parquet file containing faiss_row to external_id
        mappings.
    chunks_parquet : str
        Path to the chunks Parquet file containing chunk metadata (uri, lines,
        language, text).

    Returns
    -------
    IdMapMeta
        Metadata describing the materialized table including checksum, row count,
        and whether a refresh occurred.
    """
    DuckDBCatalog._ensure_idmap_tables(conn)
    ensure_faiss_idmap_view(
        conn,
        idmap_parquet=idmap_parquet,
        chunks_parquet=chunks_parquet,
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faiss_idmap_mat_meta (
            parquet_path TEXT PRIMARY KEY,
            parquet_hash TEXT NOT NULL,
            row_count BIGINT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT
        )
        """
    )
    checksum = _parquet_hash(idmap_parquet)
    row = conn.execute(
        """
        SELECT parquet_hash, row_count
          FROM faiss_idmap_mat_meta
         WHERE parquet_path = ?
      ORDER BY updated_at DESC
         LIMIT 1
        """,
        [idmap_parquet],
    ).fetchone()
    if row and row[0] == checksum:
        count_row = conn.execute("SELECT COUNT(*) FROM faiss_idmap_mat").fetchone()
        row_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
        return IdMapMeta(
            parquet_path=idmap_parquet,
            parquet_hash=checksum,
            row_count=row_count,
            refreshed=False,
        )

    conn.execute("DROP TABLE IF EXISTS faiss_idmap_mat")
    conn.execute("CREATE TABLE faiss_idmap_mat AS SELECT * FROM v_faiss_join")
    row_count = (conn.execute("SELECT COUNT(*) FROM faiss_idmap_mat").fetchone() or (0,))[0]
    conn.execute(
        "DELETE FROM faiss_idmap_mat_meta WHERE parquet_path = ?",
        [idmap_parquet],
    )
    conn.execute(
        """
        INSERT INTO faiss_idmap_mat_meta(parquet_path, parquet_hash, row_count, updated_at, checksum)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
        """,
        [idmap_parquet, checksum, int(row_count or 0), checksum],
    )
    return IdMapMeta(
        parquet_path=idmap_parquet,
        parquet_hash=checksum,
        row_count=int(row_count or 0),
        refreshed=True,
    )


__all__ = [
    "DuckDBCatalog",
    "IdMapMeta",
    "StructureAnnotations",
    "ensure_faiss_idmap_view",
    "refresh_faiss_idmap_materialized",
    "relation_exists",
]
