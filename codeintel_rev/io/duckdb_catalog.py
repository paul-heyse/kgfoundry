"""DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypedDict, Unpack, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_dao import (
    DuckDBQueryBuilder,
    DuckDBQueryOptions,
    create_chunk_symbols_view,
    create_pool_coverage_view,
    ensure_chunks,
    ensure_faiss_idmap_view,
    ensure_v_faiss_join,
    materialize_v_faiss_join,
)
from codeintel_rev.io.duckdb_dao import (
    refresh_faiss_idmap_materialized as _dao_refresh_faiss_idmap_materialized,
)
from codeintel_rev.io.duckdb_dao import (
    relation_exists as _dao_relation_exists,
)
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.duckdb_schema import (
    SQL_CREATE_CALL_EDGES_TABLE,
    SQL_CREATE_CALL_NODES_TABLE,
    SQL_CREATE_CFG_BLOCKS_TABLE,
    SQL_CREATE_CFG_EDGES_TABLE,
    SQL_CREATE_DFG_EDGES_TABLE,
    SQL_CREATE_GOID_XWALK_TABLE,
    SQL_CREATE_GOIDS_TABLE,
    SQL_CREATE_V_GOID_BY_SYMBOL,
    SQL_INDEX_CALL_EDGES_CALLEE,
    SQL_INDEX_CFG_BLOCKS_FUNCTION,
    SQL_INDEX_DFG_SYMBOL,
    SQL_INDEX_GOID_XWALK_SYMBOL,
    SQL_INDEX_GOIDS_PATH_KIND,
    VIEW_V_FAISS_JOIN,
    IdMapMeta,
)
from codeintel_rev.io.parquet_store import extract_embeddings
from codeintel_rev.mcp_server.scope_utils import (
    LANGUAGE_EXTENSIONS,
    path_matches_glob,
)
from codeintel_rev.typing import NDArrayF32

relation_exists = _dao_relation_exists
if TYPE_CHECKING:
    import duckdb
    import numpy as np

    from codeintel_rev.ids.goid import GOID, CrosswalkRow
else:
    duckdb = cast("duckdb", LazyModule("duckdb", "DuckDB catalog operations"))
    np = cast("np", LazyModule("numpy", "DuckDB catalog embeddings"))
    GOID = Any
    CrosswalkRow = Mapping[str, object]

LOGGER = logging.getLogger(__name__)
_PARQUET_MAGIC = b"PAR1"

_SQL_INSERT_GOIDS = """
INSERT OR REPLACE INTO "goids"(
    goid_h128,
    urn,
    repo,
    commit,
    rel_path,
    language,
    kind,
    qualname,
    start_line,
    end_line
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_GOID_XWALK = """
INSERT OR REPLACE INTO "goid_xwalk"(
    goid_h128,
    scip_symbol,
    chunk_id,
    chunk_row_id,
    cst_node_id,
    ast_node_type,
    git_blob_sha,
    git_commit_sha,
    evidence_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_CALL_NODE = """
INSERT OR REPLACE INTO "call_nodes"(
    goid_h128,
    language,
    kind,
    arity,
    is_public,
    rel_path
) VALUES (?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_CALL_EDGE = """
INSERT OR REPLACE INTO "call_edges"(
    caller_goid_h128,
    callee_goid_h128,
    callsite_path,
    callsite_line,
    callsite_col,
    language,
    kind,
    resolved_via,
    confidence,
    evidence_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_CFG_BLOCK = """
INSERT OR REPLACE INTO "cfg_blocks"(
    function_goid_h128,
    block_idx,
    kind,
    start_line,
    end_line,
    stmts_json,
    in_degree,
    out_degree
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_CFG_EDGE = """
INSERT OR REPLACE INTO "cfg_edges"(
    function_goid_h128,
    src_block_idx,
    dst_block_idx,
    edge_type,
    cond_json
) VALUES (?, ?, ?, ?, ?)
"""

_SQL_INSERT_DFG_EDGE = """
INSERT OR REPLACE INTO "dfg_edges"(
    function_goid_h128,
    src_block_idx,
    dst_block_idx,
    src_symbol,
    dst_symbol,
    via_phi,
    use_kind
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def _escape_identifier(expr: str) -> str:
    """Return a DuckDB-escaped identifier string.

    Parameters
    ----------
    expr : str
        Identifier or column reference to escape for inclusion in SQL.

    Returns
    -------
    str
        Escaped identifier ready for substitution into SQL statements.
    """
    escape_fn = cast("Callable[[str], str] | None", getattr(duckdb, "escape_identifier", None))
    if callable(escape_fn):
        return str(escape_fn(expr))
    escaped = expr.replace('"', '""')
    return f'"{escaped}"'


def _is_valid_parquet_file(path: Path) -> bool:
    """Return ``True`` when ``path`` appears to contain a valid Parquet file.

    Parameters
    ----------
    path : Path
        File path to check for Parquet format.

    Returns
    -------
    bool
        ``True`` when both the header and footer contain the Parquet magic value.
    """
    try:
        if path.stat().st_size < len(_PARQUET_MAGIC) * 2:
            return False
        with path.open("rb") as handle:
            header = handle.read(len(_PARQUET_MAGIC))
            if header != _PARQUET_MAGIC:
                return False
            handle.seek(-len(_PARQUET_MAGIC), os.SEEK_END)
            footer = handle.read(len(_PARQUET_MAGIC))
            return footer == _PARQUET_MAGIC
    except (OSError, ValueError):
        return False


def _goid_params(entry: GOID | Mapping[str, object]) -> tuple[object, ...]:
    if isinstance(entry, Mapping):
        return (
            entry.get("h128") or entry.get("goid_h128"),
            entry.get("urn"),
            entry.get("repo"),
            entry.get("commit"),
            entry.get("rel_path"),
            entry.get("language"),
            entry.get("kind"),
            entry.get("qualname"),
            entry.get("start_line"),
            entry.get("end_line"),
        )
    return (
        entry.h128,
        entry.urn,
        entry.repo,
        entry.commit,
        entry.rel_path,
        entry.language,
        entry.kind,
        entry.qualname,
        entry.start_line,
        entry.end_line,
    )


def _crosswalk_params(row: CrosswalkRow | Mapping[str, object]) -> tuple[object, ...] | None:
    payload: Mapping[str, object]
    if isinstance(row, Mapping):
        payload = row
    else:  # pragma: no cover - defensive
        payload = {
            "goid_h128": getattr(row, "goid_h128", None),
            "scip_symbol": getattr(row, "scip_symbol", None),
            "chunk_id": getattr(row, "chunk_id", None),
            "chunk_row_id": getattr(row, "chunk_row_id", None),
            "cst_node_id": getattr(row, "cst_node_id", None),
            "ast_node_type": getattr(row, "ast_node_type", None),
            "git_blob_sha": getattr(row, "git_blob_sha", None),
            "git_commit_sha": getattr(row, "git_commit_sha", None),
            "evidence_json": getattr(row, "evidence_json", None),
        }
    goid_h128 = payload.get("goid_h128")
    if goid_h128 is None:
        return None
    evidence = payload.get("evidence_json")
    evidence_json = json.dumps(evidence) if evidence is not None else None
    return (
        goid_h128,
        payload.get("scip_symbol"),
        payload.get("chunk_id"),
        payload.get("chunk_row_id"),
        payload.get("cst_node_id"),
        payload.get("ast_node_type"),
        payload.get("git_blob_sha"),
        payload.get("git_commit_sha"),
        evidence_json,
    )


def _call_node_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("goid_h128"),
        row.get("language"),
        row.get("kind"),
        row.get("arity"),
        row.get("is_public"),
        row.get("rel_path"),
    )


def _call_edge_params(row: Mapping[str, object]) -> tuple[object, ...]:
    evidence = row.get("evidence_json")
    evidence_json = json.dumps(evidence) if evidence is not None else None
    return (
        row.get("caller_goid_h128"),
        row.get("callee_goid_h128"),
        row.get("callsite_path"),
        row.get("callsite_line"),
        row.get("callsite_col"),
        row.get("language"),
        row.get("kind"),
        row.get("resolved_via"),
        row.get("confidence"),
        evidence_json,
    )


def _cfg_block_params(row: Mapping[str, object]) -> tuple[object, ...]:
    stmts = row.get("stmts_json")
    stmts_json = json.dumps(stmts) if stmts is not None else None
    return (
        row.get("function_goid_h128"),
        row.get("block_idx"),
        row.get("kind"),
        row.get("start_line"),
        row.get("end_line"),
        stmts_json,
        row.get("in_degree"),
        row.get("out_degree"),
    )


def _cfg_edge_params(row: Mapping[str, object]) -> tuple[object, ...]:
    cond = row.get("cond_json")
    cond_json = json.dumps(cond) if cond is not None else None
    return (
        row.get("function_goid_h128"),
        row.get("src_block_idx"),
        row.get("dst_block_idx"),
        row.get("edge_type"),
        cond_json,
    )


def _dfg_edge_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("function_goid_h128"),
        row.get("src_block_idx"),
        row.get("dst_block_idx"),
        row.get("src_symbol"),
        row.get("dst_symbol"),
        row.get("via_phi"),
        row.get("use_kind"),
    )


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
    """Structured scope filter metadata used during scoped queries.

    Attributes
    ----------
    chunk_ids : tuple[int, ...]
        Tuple of chunk IDs to filter by. Empty tuple means no ID filtering.
    simple_include_globs : tuple[str, ...] | None
        Simple glob patterns for inclusion (no wildcards in directory segments).
        None means no inclusion filtering. Used for efficient SQL filtering.
    simple_exclude_globs : tuple[str, ...] | None
        Simple glob patterns for exclusion (no wildcards in directory segments).
        None means no exclusion filtering. Used for efficient SQL filtering.
    complex_include_patterns : tuple[str, ...]
        Complex glob patterns for inclusion (may contain wildcards in directory
        segments). Empty tuple means no complex inclusion filtering. Requires
        post-query filtering in Python.
    complex_exclude_patterns : tuple[str, ...]
        Complex glob patterns for exclusion (may contain wildcards in directory
        segments). Empty tuple means no complex exclusion filtering. Requires
        post-query filtering in Python.
    language_extensions : frozenset[str]
        Set of file extensions to filter by language. Empty set means no
        language filtering. Extensions should include the leading dot (e.g.,
        {".py", ".ts"}).
    """

    chunk_ids: tuple[int, ...]
    simple_include_globs: tuple[str, ...] | None
    simple_exclude_globs: tuple[str, ...] | None
    complex_include_patterns: tuple[str, ...]
    complex_exclude_patterns: tuple[str, ...]
    language_extensions: frozenset[str]

    @property
    def has_complex_globs(self) -> bool:
        """Return ``True`` when complex include/exclude patterns exist.

        Returns
        -------
        bool
            True if either complex_include_patterns or complex_exclude_patterns
            contains any patterns, False otherwise.
        """
        return bool(self.complex_include_patterns or self.complex_exclude_patterns)


@dataclass(slots=True, frozen=True)
class StructureAnnotations:
    """Structure-aware metadata joined onto explainability pools.

    Attributes
    ----------
    uri : str
        File URI or path identifier for the chunk. Matches the URI field
        from chunk records.
    symbol_hits : tuple[str, ...]
        Tuple of SCIP symbol identifiers that match the chunk. Empty tuple
        if no symbols match. Symbols are in SCIP format (e.g.,
        "python kgfoundry.core#Function.main").
    ast_node_kinds : tuple[str, ...]
        Tuple of AST node kind identifiers found in the chunk. Empty tuple
        if no AST nodes match. Node kinds are language-specific (e.g.,
        "FunctionDef", "ClassDef" for Python).
    cst_matches : tuple[str, ...]
        Tuple of CST (Concrete Syntax Tree) node kind identifiers found in
        the chunk. Empty tuple if no CST nodes match. Used for structure-aware
        search and explainability.
    """

    uri: str
    symbol_hits: tuple[str, ...]
    ast_node_kinds: tuple[str, ...]
    cst_matches: tuple[str, ...]


@dataclass(frozen=True)
class _StructMaterializationPlan:
    """Precomputed SQL statements for struct table materialization.

    Attributes
    ----------
    create_sql : str
        SQL statement to create the materialized table structure (empty table).
    meta_create_sql : str
        SQL statement to create the metadata table for tracking materialization
        state (checksum, updated_at timestamp).
    meta_select_sql : str
        SQL statement to select the checksum from the metadata table for
        change detection.
    delete_sql : str
        SQL statement to delete all rows from the materialized table before
        refresh.
    insert_sql : str
        SQL statement to insert rows from the source view/table into the
        materialized table.
    meta_delete_sql : str
        SQL statement to delete metadata rows before updating checksum.
    meta_insert_sql : str
        SQL statement to insert checksum and timestamp into the metadata table.
    count_sql : str
        SQL statement to count rows in the materialized table for validation.
    """

    create_sql: str
    meta_create_sql: str
    meta_select_sql: str
    delete_sql: str
    insert_sql: str
    meta_delete_sql: str
    meta_insert_sql: str
    count_sql: str


_STRUCT_MATERIALIZATION_PLANS: dict[str, _StructMaterializationPlan] = {
    "modules_mat": _StructMaterializationPlan(
        create_sql="CREATE TABLE IF NOT EXISTS modules_mat AS SELECT * FROM modules LIMIT 0",
        meta_create_sql="""
        CREATE TABLE IF NOT EXISTS modules_mat_meta (
            checksum   TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        meta_select_sql="SELECT checksum FROM modules_mat_meta LIMIT 1",
        delete_sql="DELETE FROM modules_mat",
        insert_sql="INSERT INTO modules_mat SELECT * FROM modules",
        meta_delete_sql="DELETE FROM modules_mat_meta",
        meta_insert_sql="INSERT INTO modules_mat_meta(checksum, updated_at) VALUES (?, CURRENT_TIMESTAMP)",
        count_sql="SELECT COUNT(*) FROM modules_mat",
    ),
    "scip_occurrences_mat": _StructMaterializationPlan(
        create_sql="CREATE TABLE IF NOT EXISTS scip_occurrences_mat AS SELECT * FROM scip_occurrences LIMIT 0",
        meta_create_sql="""
        CREATE TABLE IF NOT EXISTS scip_occurrences_mat_meta (
            checksum   TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        meta_select_sql="SELECT checksum FROM scip_occurrences_mat_meta LIMIT 1",
        delete_sql="DELETE FROM scip_occurrences_mat",
        insert_sql="INSERT INTO scip_occurrences_mat SELECT * FROM scip_occurrences",
        meta_delete_sql="DELETE FROM scip_occurrences_mat_meta",
        meta_insert_sql="INSERT INTO scip_occurrences_mat_meta(checksum, updated_at) VALUES (?, CURRENT_TIMESTAMP)",
        count_sql="SELECT COUNT(*) FROM scip_occurrences_mat",
    ),
    "ast_nodes_mat": _StructMaterializationPlan(
        create_sql="CREATE TABLE IF NOT EXISTS ast_nodes_mat AS SELECT * FROM ast_nodes LIMIT 0",
        meta_create_sql="""
        CREATE TABLE IF NOT EXISTS ast_nodes_mat_meta (
            checksum   TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        meta_select_sql="SELECT checksum FROM ast_nodes_mat_meta LIMIT 1",
        delete_sql="DELETE FROM ast_nodes_mat",
        insert_sql="INSERT INTO ast_nodes_mat SELECT * FROM ast_nodes",
        meta_delete_sql="DELETE FROM ast_nodes_mat_meta",
        meta_insert_sql="INSERT INTO ast_nodes_mat_meta(checksum, updated_at) VALUES (?, CURRENT_TIMESTAMP)",
        count_sql="SELECT COUNT(*) FROM ast_nodes_mat",
    ),
    "cst_nodes_mat": _StructMaterializationPlan(
        create_sql="CREATE TABLE IF NOT EXISTS cst_nodes_mat AS SELECT * FROM cst_nodes LIMIT 0",
        meta_create_sql="""
        CREATE TABLE IF NOT EXISTS cst_nodes_mat_meta (
            checksum   TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        meta_select_sql="SELECT checksum FROM cst_nodes_mat_meta LIMIT 1",
        delete_sql="DELETE FROM cst_nodes_mat",
        insert_sql="INSERT INTO cst_nodes_mat SELECT * FROM cst_nodes",
        meta_delete_sql="DELETE FROM cst_nodes_mat_meta",
        meta_insert_sql="INSERT INTO cst_nodes_mat_meta(checksum, updated_at) VALUES (?, CURRENT_TIMESTAMP)",
        count_sql="SELECT COUNT(*) FROM cst_nodes_mat",
    ),
}


@dataclass(slots=True)
class DuckDBCatalogOptions:
    """Optional configuration bundle for DuckDB catalog instantiation.

    Attributes
    ----------
    materialize : bool, optional
        Whether to materialize views immediately when creating the catalog.
        If True, views are computed and persisted; if False, views are
        registered but not computed until explicitly materialized. Defaults
        to False.
    manager : DuckDBManager | None, optional
        Optional DuckDB manager instance for connection management. If None,
        a new manager is created. Defaults to None.
    log_queries : bool | None, optional
        Whether to log SQL queries executed by the catalog. If None, uses
        manager's default logging setting. Defaults to None.
    repo_root : Path | None, optional
        Optional repository root path for path resolution. If None, uses
        manager's default. Defaults to None.
    query_builder_factory : Callable[[], DuckDBQueryBuilder] | None, optional
        Optional factory function for creating query builder instances. If None,
        uses default query builder. Defaults to None.
    """

    materialize: bool = False
    manager: DuckDBManager | None = None
    log_queries: bool | None = None
    repo_root: Path | None = None
    query_builder_factory: Callable[[], DuckDBQueryBuilder] | None = None


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
        sql = """
            SELECT c.*
            FROM chunks AS c
            JOIN UNNEST(?) WITH ORDINALITY AS ids(id, position)
                ON c.id = ids.id
            ORDER BY ids.position
            """
        params = [list(ids)]
        with catalog.readonly_connection() as conn:
            relation = conn.execute(sql, params)
            return DuckDBCatalog.catalog_payload(relation, query_name="query_by_ids")

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
        with catalog.readonly_connection() as conn:
            base_rows = self._fetch_annotation_rows(conn, unique_ids)
            annotations, boundaries = self._initialize_annotation_maps(base_rows)
            if not annotations:
                return {}
            if relation_exists(conn, "chunk_symbols"):
                self._attach_chunk_symbols(conn, unique_ids, annotations)
            if relation_exists(conn, "ast_nodes"):
                self._attach_ast_nodes(conn, boundaries, annotations)
            if relation_exists(conn, "cst_nodes"):
                path_column = self._resolve_cst_path_column(conn)
                self._attach_cst_nodes(conn, path_column, boundaries, annotations)
        return self._coerce_annotation_payload(unique_ids, annotations)

    @staticmethod
    def _fetch_annotation_rows(
        conn: duckdb.DuckDBPyConnection,
        unique_ids: Sequence[int],
    ) -> list[tuple[int, str, int | None, int | None, Sequence[str] | None]]:
        """Fetch chunk annotation rows from the chunks table.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to execute query on.
        unique_ids : Sequence[int]
            Chunk IDs to fetch annotations for.

        Returns
        -------
        list[tuple[int, str, int | None, int | None, Sequence[str] | None]]
            Rows containing (id, uri, start_line, end_line, symbols) for each chunk.
        """
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
        """Initialize annotation maps from chunk rows.

        Parameters
        ----------
        rows : Sequence[tuple[int, str, int | None, int | None, Sequence[str] | None]]
            Chunk rows from _fetch_annotation_rows.

        Returns
        -------
        tuple[dict[int, dict[str, object]], dict[int, tuple[int, int]]]
            Tuple of (annotations dict, boundaries dict) initialized with URI,
            symbol_hits, ast_node_kinds, cst_matches, and line boundaries.
        """
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
        """Attach symbol hits from chunk_symbols table to annotation maps.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to query chunk_symbols table.
        unique_ids : Sequence[int]
            Chunk IDs to fetch symbols for.
        annotations : dict[int, dict[str, object]]
            Annotation maps to update with symbol_hits.
        """
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
        """Attach AST node kinds from ast_nodes table to annotation maps.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to query ast_nodes table.
        boundaries : Mapping[int, tuple[int, int]]
            Mapping of chunk IDs to (start_line, end_line) boundaries.
        annotations : dict[int, dict[str, object]]
            Annotation maps to update with ast_node_kinds.
        """
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
        """Determine which column name is used for paths in cst_nodes table.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to probe cst_nodes schema.

        Returns
        -------
        str
            Column name ("uri" or "path") that exists in cst_nodes, defaults to "uri".
        """
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
        """Attach CST node kinds from cst_nodes table to annotation maps.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to query cst_nodes table.
        path_column : str
            Column name to use for path matching ("uri" or "path").
        boundaries : Mapping[int, tuple[int, int]]
            Mapping of chunk IDs to (start_line, end_line) boundaries.
        annotations : dict[int, dict[str, object]]
            Annotation maps to update with cst_matches.
        """
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
        except duckdb.Error:  # pragma: no cover - schema may evolve
            return

    @staticmethod
    def _coerce_annotation_payload(
        ordered_ids: Sequence[int],
        annotations: Mapping[int, dict[str, object]],
    ) -> dict[int, StructureAnnotations]:
        """Convert annotation dictionaries to StructureAnnotations objects.

        Parameters
        ----------
        ordered_ids : Sequence[int]
            Chunk IDs in the order they should appear in the result.
        annotations : Mapping[int, dict[str, object]]
            Raw annotation dictionaries keyed by chunk ID.

        Returns
        -------
        dict[int, StructureAnnotations]
            StructureAnnotations objects keyed by chunk ID, preserving order.
        """
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
    """Legacy options dictionary for backward compatibility.

    Attributes
    ----------
    materialize : bool, optional
        Whether to materialize views as tables.
    manager : DuckDBManager | None, optional
        DuckDB manager instance for connection pooling.
    log_queries : bool, optional
        Whether to log executed SQL queries.
    repo_root : Path, optional
        Repository root directory path.
    """

    materialize: bool
    manager: DuckDBManager | None
    log_queries: bool
    repo_root: Path


class DuckDBCatalog(_DuckDBQueryMixin):  # noqa: PLR0904 - rich API surface
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
                allowed = {
                    "materialize",
                    "manager",
                    "log_queries",
                    "repo_root",
                    "query_builder_factory",
                }
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
        builder_factory = options.query_builder_factory or DuckDBQueryBuilder
        self._query_builder = builder_factory()
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
    def readonly_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a read-only DuckDB connection for hydration queries.

        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection opened in read-only mode for catalog reads.
        """
        with self._readonly_connection() as conn:
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

    @staticmethod
    def _log_query(_sql: str, _params: object | None = None) -> None:
        """Compatibility stub retained after removing catalog logging."""
        return

    @staticmethod
    def catalog_payload(
        relation: duckdb.DuckDBPyRelation | duckdb.DuckDBPyConnection,
        *,
        query_name: str,
    ) -> list[dict[str, object]]:
        """Convert a DuckDB relation into a list of row dictionaries.

        Parameters
        ----------
        relation : duckdb.DuckDBPyRelation | duckdb.DuckDBPyConnection
            Relation or cursor containing the query result.
        query_name : str
            Logical name of the query for logging.

        Returns
        -------
        list[dict[str, object]]
            Materialized rows keyed by column name.
        """
        rows = relation.fetchall()
        cols = [desc[0] for desc in relation.description]
        payload = [dict(zip(cols, row, strict=True)) for row in rows]
        LOGGER.debug(
            "duckdb catalog query complete",
            extra={"query_name": query_name, "row_count": len(payload)},
        )
        return payload

    def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create required views and tables to hydrate chunk metadata."""
        self._install_chunks_view(conn)
        self._install_optional_views(conn)
        self._ensure_faiss_idmap_view(conn, None)
        self._ensure_faiss_join_view(conn)

    def _install_chunks_view(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Install the chunks view from Parquet files if it doesn't exist.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        """
        if relation_exists(conn, "chunks"):
            return
        parquet_glob = str(self.vectors_dir / "**/*.parquet")
        parquet_exists = any(self.vectors_dir.rglob("*.parquet"))
        ensure_chunks(
            conn,
            parquet_glob=parquet_glob,
            materialize=self.materialize,
            parquet_exists=parquet_exists,
        )

    def _install_optional_views(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Install optional enrichment views (modules, SCIP, AST, CST, symbols).

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create views on.
        """
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
        """Install a view reading from a Parquet file.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        view_name : str
            Name for the created view.
        source : Path
            Path to the Parquet file to read from.

        Returns
        -------
        bool
            True if view was created, False if source file doesn't exist.
        """
        if not source.exists():
            return False
        sql = "SELECT * FROM read_parquet(?)"
        params = [str(source)]
        self._log_query(sql, params)
        relation = conn.sql(sql, params=params)
        relation.create_view(view_name, replace=True)
        return True

    def _install_json_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
        source: Path,
    ) -> bool:
        """Install a view reading from a JSON/JSONL file.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        view_name : str
            Name for the created view.
        source : Path
            Path to the JSON/JSONL file to read from.

        Returns
        -------
        bool
            True if view was created, False if source file doesn't exist.
        """
        if not source.exists():
            return False
        sql = "SELECT * FROM read_json_auto(?)"
        params = [str(source)]
        self._log_query(sql, params)
        relation = conn.sql(sql, params=params)
        relation.create_view(view_name, replace=True)
        return True

    @staticmethod
    def _install_chunk_symbols_view(conn: duckdb.DuckDBPyConnection) -> None:
        """Install view that unnests symbols from chunks into chunk_symbols format.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        """
        try:
            create_chunk_symbols_view(conn)
        except duckdb.Error:  # pragma: no cover - defensive fallback for legacy schemas
            return

    def _install_struct_view_if_exists(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        view_name: str,
        source: Path | None,
    ) -> None:
        """Install a structure view from Parquet if source file exists.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        view_name : str
            Name for the created view.
        source : Path | None
            Path to Parquet file, or None to skip installation.
        """
        if source and source.exists():
            self._install_parquet_view(conn, view_name, source)

    def _materialize_struct_table_if_exists(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        plan_key: str,
        asset_path: Path | None,
    ) -> None:
        """Materialize a structure table from Parquet if asset exists.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create table on.
        plan_key : str
            Key to lookup materialization plan from _STRUCT_MATERIALIZATION_PLANS.
        asset_path : Path | None
            Path to Parquet asset, or None to skip materialization.
        """
        if asset_path and asset_path.exists():
            plan = _STRUCT_MATERIALIZATION_PLANS[plan_key]
            self._materialize_struct_table(
                conn,
                plan=plan,
                checksum=_file_checksum(asset_path),
            )

    @staticmethod
    def _materialize_struct_table(
        conn: duckdb.DuckDBPyConnection,
        *,
        plan: _StructMaterializationPlan,
        checksum: str,
    ) -> None:
        """Materialize a struct table using a precomputed SQL plan."""
        conn.execute(plan.create_sql)
        conn.execute(plan.meta_create_sql)
        row = conn.execute(plan.meta_select_sql).fetchone()
        if row and row[0] == checksum:
            return

        conn.execute(plan.delete_sql)
        conn.execute(plan.insert_sql)
        conn.execute(plan.meta_delete_sql)
        conn.execute(plan.meta_insert_sql, [checksum])
        conn.execute(plan.count_sql).fetchone()

    @staticmethod
    @staticmethod
    def _ensure_faiss_join_view(conn: duckdb.DuckDBPyConnection) -> None:
        """Expose chunks joined with FAISS ID map for deterministic hydration."""
        ensure_v_faiss_join(conn)

    def _ensure_faiss_idmap_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        override_path: Path | None,
    ) -> None:
        """Ensure FAISS ID map view exists, using override path if provided.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB connection to create view on.
        override_path : Path | None
            Optional override path for ID map Parquet file, otherwise uses catalog's
            configured idmap path.
        """
        target = override_path or self._idmap_path
        if target and not target.exists():
            target = None
        ensure_faiss_idmap_view(conn, idmap_parquet=target)

    def ensure_faiss_idmap_views(self, idmap_path: Path | None = None) -> None:
        """Install/refresh FAISS id map views from a specific Parquet file."""
        with self.connection() as conn:
            self._ensure_faiss_idmap_view(conn, idmap_path)
            self._ensure_faiss_join_view(conn)

    def ensure_struct_views(
        self,
        *,
        modules_parquet: Path | None = None,
        scip_occurrences_parquet: Path | None = None,
        ast_nodes_parquet: Path | None = None,
        cst_nodes_parquet: Path | None = None,
        materialize: bool = False,
    ) -> None:
        """Register structure-aware Parquet assets and optional materialized tables."""

        def _resolve(path: Path | None) -> Path | None:
            """Resolve and expand user home directory in path.

            Parameters
            ----------
            path : Path | None
                Path to resolve, or None.

            Returns
            -------
            Path | None
                Resolved absolute path, or None if input was None.
            """
            if path is None:
                return None
            return path.expanduser().resolve()

        modules_path = _resolve(modules_parquet)
        scip_path = _resolve(scip_occurrences_parquet)
        ast_path = _resolve(ast_nodes_parquet)
        cst_path = _resolve(cst_nodes_parquet)

        view_specs = (
            ("modules", modules_path),
            ("scip_occurrences", scip_path),
            ("ast_nodes", ast_path),
            ("cst_nodes", cst_path),
        )

        with self.connection() as conn:
            for view_name, path in view_specs:
                self._install_struct_view_if_exists(conn, view_name=view_name, source=path)
            self._install_chunk_symbols_view(conn)

        if not materialize:
            return

        materialize_specs = (
            ("modules_mat", modules_path),
            ("scip_occurrences_mat", scip_path),
            ("ast_nodes_mat", ast_path),
            ("cst_nodes_mat", cst_path),
        )

        with self.connection() as conn:
            for plan_key, asset_path in materialize_specs:
                self._materialize_struct_table_if_exists(
                    conn,
                    plan_key=plan_key,
                    asset_path=asset_path,
                )

    def materialize_faiss_join(self) -> int:
        """Persist ``v_faiss_join`` into ``faiss_join_mat`` for BI workloads.

        Returns
        -------
        int
            Number of rows materialized into ``faiss_join_mat``.
        """
        with self.connection() as conn:
            if not relation_exists(conn, VIEW_V_FAISS_JOIN):
                return 0
            rows = materialize_v_faiss_join(conn)
            LOGGER.debug("faiss_join_mat rows: %d", rows)
            return rows

    def set_idmap_path(self, path: Path) -> None:
        """Override the FAISS id map path used for view installation."""
        self._idmap_path = path.resolve()

    @staticmethod
    def _resolve_idmap_path(path: Path) -> Path:
        """Resolve a user-provided idmap path, ensuring it exists on disk.

        Parameters
        ----------
        path : Path
            User-provided path to the idmap Parquet file. May be relative or
            contain tilde expansion.

        Returns
        -------
        Path
            Absolute path to the idmap Parquet file.

        Raises
        ------
        FileNotFoundError
            If the provided path does not exist after resolution.
        """
        candidate = path.expanduser()
        resolved = candidate if candidate.is_absolute() else candidate.resolve()
        if not resolved.exists():
            message = f"FAISS idmap Parquet not found: {resolved}"
            raise FileNotFoundError(message)
        return resolved

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
        resolved = self._resolve_idmap_path(path)
        self.set_idmap_path(resolved)
        stats = self.refresh_faiss_idmap_mat_if_changed(resolved)
        if materialize:
            self.materialize_faiss_join()
        return stats

    def ensure_pool_views(self, pool_path: Path) -> None:
        """Expose the latest evaluator pool and coverage join as DuckDB views."""
        with self.connection() as conn:
            sql = "SELECT * FROM read_parquet(?)"
            params = [str(pool_path)]
            self._log_query(sql, params)
            relation = conn.sql(sql, params=params)
            relation.create_view("v_faiss_pool", replace=True)
            try:
                create_pool_coverage_view(conn, include_modules=True)
            except duckdb.Error:
                create_pool_coverage_view(conn, include_modules=False)

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
        resolved = self._resolve_idmap_path(idmap_parquet)
        checksum = _compute_checksum_for_idmap(resolved, self.vectors_dir)
        with self._manager.connection() as conn:
            self._ensure_views(conn)
            ensure_faiss_idmap_view(conn, idmap_parquet=resolved)
            ensure_v_faiss_join(conn)
            meta = _dao_refresh_faiss_idmap_materialized(
                conn,
                _idmap_parquet=resolved,
                checksum=checksum,
            )
            stats: dict[str, Any] = {
                "refreshed": meta.refreshed,
                "checksum": meta.checksum,
                "rows": meta.rows,
            }
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
        with self.readonly_connection() as conn:
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

        results: list[dict] = []
        spec = self._build_scope_filter_spec(
            ids,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            languages=languages,
        )
        if not (languages and not spec.language_extensions):
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
            with self.readonly_connection() as conn:
                relation = conn.execute(sql, sql_params)
                results = self.catalog_payload(
                    relation,
                    query_name="query_by_filters",
                )
            results = self._apply_complex_glob_filters(
                results,
                spec.complex_include_patterns,
                spec.complex_exclude_patterns,
            )
            results = self._apply_language_filters(results, spec.language_extensions)

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

    @staticmethod
    def _determine_filter_type(
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        languages: list[str] | None,
    ) -> str:
        """Format the filter type label (observability removed).

        Determines the type of scope filtering being applied based on the
        presence of glob patterns and language filters.

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

    def _get_symbols_for_chunk(self, chunk_id: int) -> list[str]:
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
        with self.readonly_connection() as conn:
            if relation_exists(conn, "v_chunk_symbols"):
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

        with self.readonly_connection() as conn:
            relation = conn.execute(sql, params)
            return self.catalog_payload(
                relation,
                query_name="get_chunks_by_uri",
            )

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

        with self.connection() as conn:
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
        return ordered_ids, vectors

    def upsert_goids(self, goids: Iterable[GOID | Mapping[str, object]]) -> int:
        """Insert or update GOID registry rows.

        Parameters
        ----------
        goids : Iterable[GOID | Mapping[str, object]]
            Iterable of GOID objects or dictionaries to insert or update
            in the goids table.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid GOIDs were provided or all GOIDs were filtered out.
        """
        rows: list[tuple[object, ...]] = []
        for goid in goids:
            params = _goid_params(goid)
            if params[0] is None:
                continue
            rows.append(params)
        if not rows:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_GOIDS_TABLE)
            conn.execute(SQL_CREATE_GOID_XWALK_TABLE)
            conn.execute(SQL_INDEX_GOIDS_PATH_KIND)
            conn.executemany(_SQL_INSERT_GOIDS, rows)
            conn.execute(SQL_CREATE_V_GOID_BY_SYMBOL)
        return len(rows)

    def upsert_goid_xwalk(self, rows: Iterable[CrosswalkRow | Mapping[str, object]]) -> int:
        """Insert or update GOID crosswalk rows.

        Parameters
        ----------
        rows : Iterable[CrosswalkRow | Mapping[str, object]]
            Iterable of crosswalk row objects or dictionaries to insert or
            update in the goid_xwalk table.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid crosswalk rows were provided or all rows were filtered out.
        """
        payload: list[tuple[object, ...]] = []
        for row in rows:
            params = _crosswalk_params(row)
            if params is None:
                continue
            payload.append(params)
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_GOID_XWALK_TABLE)
            conn.execute(SQL_INDEX_GOID_XWALK_SYMBOL)
            conn.executemany(_SQL_INSERT_GOID_XWALK, payload)
            conn.execute(SQL_CREATE_V_GOID_BY_SYMBOL)
        return len(payload)

    def find_goid_by_symbol(self, scip_symbol: str) -> list[dict[str, object]]:
        """Return GOID rows that match a SCIP symbol.

        Parameters
        ----------
        scip_symbol : str
            SCIP symbol identifier to search for in the crosswalk table.

        Returns
        -------
        list[dict[str, object]]
            List of GOID dictionary rows matching the SCIP symbol. Each
            dictionary contains GOID attributes (urn, h128, repo, commit,
            rel_path, language, kind, qualname, start_line, end_line).
            Returns empty list if symbol is empty or no matches found.
        """
        if not scip_symbol:
            return []
        with self.readonly_connection() as conn:
            conn.execute(SQL_CREATE_V_GOID_BY_SYMBOL)
            relation = conn.execute(
                """
                SELECT go.*
                FROM goids AS go
                JOIN goid_xwalk AS gx USING (goid_h128)
                WHERE gx.scip_symbol = ?
                """,
                [scip_symbol],
            )
            return self.catalog_payload(relation, query_name="goid-by-symbol")

    def resolve_goid_by_path_span(
        self,
        rel_path: str,
        *,
        kind: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> list[dict[str, object]]:
        """Resolve GOIDs for a repo-relative path filtered by optional span.

        Parameters
        ----------
        rel_path : str
            Repository-relative file path to search for GOIDs.
        kind : str | None, optional
            Optional code element kind filter (e.g., "function", "class").
            If None, all kinds are included.
        start_line : int | None, optional
            Optional starting line number filter. GOIDs with start_line <=
            this value or NULL are included.
        end_line : int | None, optional
            Optional ending line number filter. GOIDs with end_line >=
            this value or NULL are included.

        Returns
        -------
        list[dict[str, object]]
            List of GOID dictionary rows matching the path and span filters.
            Results are ordered by start_line with NULL values first.
            Each dictionary contains all GOID attributes.
        """
        clauses = ["rel_path = ?"]
        params: list[object] = [rel_path]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if start_line is not None:
            clauses.append("(start_line IS NULL OR start_line <= ?)")
            params.append(start_line)
        if end_line is not None:
            clauses.append("(end_line IS NULL OR end_line >= ?)")
            params.append(end_line)
        sql_parts = [
            "SELECT * FROM goids WHERE ",
            " AND ".join(clauses),
            " ORDER BY start_line NULLS FIRST",
        ]
        sql = "".join(sql_parts)
        with self.readonly_connection() as conn:
            relation = conn.execute(sql, params)
            return self.catalog_payload(relation, query_name="goid-by-span")

    def crosswalk_for_goid(self, goid_h128: int) -> list[dict[str, object]]:
        """Return all crosswalk anchors for a GOID.

        Parameters
        ----------
        goid_h128 : int
            128-bit hash identifier of the GOID to look up crosswalk entries.

        Returns
        -------
        list[dict[str, object]]
            List of crosswalk row dictionaries for the specified GOID hash.
            Each dictionary contains crosswalk attributes (goid_h128,
            scip_symbol, ast_node_type, chunk_id, evidence_json, etc.).
            Returns empty list if no crosswalk entries exist for the GOID.
        """
        with self.readonly_connection() as conn:
            relation = conn.execute(
                "SELECT * FROM goid_xwalk WHERE goid_h128 = ?",
                [goid_h128],
            )
            return self.catalog_payload(relation, query_name="goid-crosswalk")

    def upsert_call_nodes(self, nodes: Iterable[Mapping[str, object]]) -> int:
        """Insert or update call graph node rows.

        Parameters
        ----------
        nodes : Iterable[Mapping[str, object]]
            Iterable of call node dictionaries to insert or update.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid nodes were provided.
        """
        payload = [_call_node_params(node) for node in nodes]
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_CALL_NODES_TABLE)
            conn.executemany(_SQL_INSERT_CALL_NODE, payload)
        return len(payload)

    def upsert_call_edges(self, edges: Iterable[Mapping[str, object]]) -> int:
        """Insert or update call graph edges.

        Parameters
        ----------
        edges : Iterable[Mapping[str, object]]
            Iterable of call edge dictionaries to insert or update.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid edges were provided.
        """
        payload = [_call_edge_params(edge) for edge in edges]
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_CALL_NODES_TABLE)
            conn.execute(SQL_CREATE_CALL_EDGES_TABLE)
            conn.execute(SQL_INDEX_CALL_EDGES_CALLEE)
            conn.executemany(_SQL_INSERT_CALL_EDGE, payload)
        return len(payload)

    def upsert_cfg_blocks(self, blocks: Iterable[Mapping[str, object]]) -> int:
        """Insert or update CFG block rows.

        Parameters
        ----------
        blocks : Iterable[Mapping[str, object]]
            Iterable of CFG block dictionaries to insert or update.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid blocks were provided.
        """
        payload = [_cfg_block_params(block) for block in blocks]
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_CFG_BLOCKS_TABLE)
            conn.execute(SQL_INDEX_CFG_BLOCKS_FUNCTION)
            conn.executemany(_SQL_INSERT_CFG_BLOCK, payload)
        return len(payload)

    def upsert_cfg_edges(self, edges: Iterable[Mapping[str, object]]) -> int:
        """Insert or update CFG edge rows.

        Parameters
        ----------
        edges : Iterable[Mapping[str, object]]
            Iterable of CFG edge dictionaries to insert or update.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid edges were provided.
        """
        payload = [_cfg_edge_params(edge) for edge in edges]
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_CFG_EDGES_TABLE)
            conn.executemany(_SQL_INSERT_CFG_EDGE, payload)
        return len(payload)

    def upsert_dfg_edges(self, edges: Iterable[Mapping[str, object]]) -> int:
        """Insert or update DFG edge rows.

        Parameters
        ----------
        edges : Iterable[Mapping[str, object]]
            Iterable of DFG edge dictionaries to insert or update.

        Returns
        -------
        int
            Number of rows successfully inserted or updated. Returns 0 if
            no valid edges were provided.
        """
        payload = [_dfg_edge_params(edge) for edge in edges]
        if not payload:
            return 0
        with self.connection() as conn:
            conn.execute(SQL_CREATE_DFG_EDGES_TABLE)
            conn.execute(SQL_INDEX_DFG_SYMBOL)
            conn.executemany(_SQL_INSERT_DFG_EDGE, payload)
        return len(payload)

    def get_callees(self, goid_h128: int, *, limit: int = 50) -> list[dict[str, object]]:
        """Return callee edges for a GOID.

        Parameters
        ----------
        goid_h128 : int
            128-bit hash identifier of the caller GOID.
        limit : int, optional
            Maximum number of callee edges to return. Defaults to 50.

        Returns
        -------
        list[dict[str, object]]
            List of call edge dictionaries where the caller matches the specified
            GOID. Edges are ordered by callsite line and column. Each dictionary
            contains caller_goid_h128, callee_goid_h128, callsite information,
            and resolution metadata.
        """
        with self.readonly_connection() as conn:
            relation = conn.execute(
                """
                SELECT *
                FROM call_edges
                WHERE caller_goid_h128 = ?
                ORDER BY callsite_line, callsite_col
                LIMIT ?
                """,
                [goid_h128, limit],
            )
            return self.catalog_payload(relation, query_name="callgraph-callees")

    def get_callers(self, goid_h128: int, *, limit: int = 50) -> list[dict[str, object]]:
        """Return caller edges for a GOID.

        Parameters
        ----------
        goid_h128 : int
            128-bit hash identifier of the callee GOID.
        limit : int, optional
            Maximum number of caller edges to return. Defaults to 50.

        Returns
        -------
        list[dict[str, object]]
            List of call edge dictionaries where the callee matches the specified
            GOID. Edges are ordered by callsite line and column. Each dictionary
            contains caller_goid_h128, callee_goid_h128, callsite information,
            and resolution metadata.
        """
        with self.readonly_connection() as conn:
            relation = conn.execute(
                """
                SELECT *
                FROM call_edges
                WHERE callee_goid_h128 = ?
                ORDER BY callsite_line, callsite_col
                LIMIT ?
                """,
                [goid_h128, limit],
            )
            return self.catalog_payload(relation, query_name="callgraph-callers")

    def get_call_graph_subgraph(
        self,
        seed_goids: Sequence[int],
        *,
        direction: str = "outbound",
        limit: int = 200,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Return call graph nodes/edges adjacent to seed GOIDs.

        Parameters
        ----------
        seed_goids : Sequence[int]
            Sequence of GOID hashes to use as seeds for subgraph extraction.
        direction : str, optional
            Direction of traversal: "outbound" (default) for callees, "inbound"
            for callers.
        limit : int, optional
            Maximum number of edges to return. Defaults to 200.

        Returns
        -------
        tuple[list[dict[str, object]], list[dict[str, object]]]
            Tuple containing:
            - List of call node dictionaries for GOIDs in the subgraph.
            - List of call edge dictionaries connecting the seed GOIDs.
            Returns empty lists if seed_goids is empty.
        """
        if not seed_goids:
            return [], []
        values = [int(value) for value in seed_goids]
        column = "callee" if direction == "inbound" else "caller"
        with self.readonly_connection() as conn:
            if column == "callee":
                relation = conn.execute(
                    """
                    SELECT *
                    FROM call_edges
                    WHERE callee_goid_h128 IN UNNEST(?)
                    LIMIT ?
                    """,
                    [values, limit],
                )
            else:
                relation = conn.execute(
                    """
                    SELECT *
                    FROM call_edges
                    WHERE caller_goid_h128 IN UNNEST(?)
                    LIMIT ?
                    """,
                    [values, limit],
                )
            edges = self.catalog_payload(relation, query_name="callgraph-subgraph-edges")
            node_ids: set[int] = set()
            for edge in edges:
                caller = edge.get("caller_goid_h128")
                if isinstance(caller, int):
                    node_ids.add(caller)
                callee = edge.get("callee_goid_h128")
                if isinstance(callee, int):
                    node_ids.add(callee)
            if not node_ids:
                return [], edges
            node_relation = conn.execute(
                """
                SELECT *
                FROM call_nodes
                WHERE goid_h128 IN UNNEST(?)
                """,
                [list(node_ids)],
            )
            nodes = self.catalog_payload(node_relation, query_name="callgraph-subgraph-nodes")
            return nodes, edges

    def cfg_for_function(self, goid_h128: int) -> dict[str, list[dict[str, object]]]:
        """Return CFG blocks/edges for a GOID.

        Parameters
        ----------
        goid_h128 : int
            128-bit hash identifier of the function GOID.

        Returns
        -------
        dict[str, list[dict[str, object]]]
            Dictionary with two keys:
            - "blocks": List of CFG block dictionaries ordered by block_idx.
            - "edges": List of CFG edge dictionaries connecting blocks.
            Returns empty lists if no CFG data exists for the function.
        """
        with self.readonly_connection() as conn:
            block_relation = conn.execute(
                """
                SELECT *
                FROM cfg_blocks
                WHERE function_goid_h128 = ?
                ORDER BY block_idx
                """,
                [goid_h128],
            )
            edge_relation = conn.execute(
                """
                SELECT *
                FROM cfg_edges
                WHERE function_goid_h128 = ?
                """,
                [goid_h128],
            )
            return {
                "blocks": self.catalog_payload(block_relation, query_name="cfg-blocks"),
                "edges": self.catalog_payload(edge_relation, query_name="cfg-edges"),
            }

    def dfg_for_function(self, goid_h128: int) -> list[dict[str, object]]:
        """Return DFG edges for a GOID.

        Parameters
        ----------
        goid_h128 : int
            128-bit hash identifier of the function GOID.

        Returns
        -------
        list[dict[str, object]]
            List of data flow graph edge dictionaries for the specified function.
            Each edge represents a data dependency between symbols. Returns empty
            list if no DFG data exists for the function.
        """
        with self.readonly_connection() as conn:
            relation = conn.execute(
                """
                SELECT *
                FROM dfg_edges
                WHERE function_goid_h128 = ?
                """,
                [goid_h128],
            )
            return self.catalog_payload(relation, query_name="dfg-edges")

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
        with self.readonly_connection() as conn:
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
        with self.readonly_connection() as conn:
            result = conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
        if result and result[0] is not None:
            self._embedding_dim_cache = len(result[0])
        else:
            self._embedding_dim_cache = 0
        return self._embedding_dim_cache


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


def _compute_checksum_for_idmap(idmap_parquet: Path, vectors_dir: Path | None) -> str:
    """Compute SHA256 checksum of ID map and associated Parquet files.

    Parameters
    ----------
    idmap_parquet : Path
        Path to the ID map Parquet file.
    vectors_dir : Path | None
        Directory containing Parquet files to include in checksum.

    Returns
    -------
    str
        Hexadecimal SHA256 checksum string.

    Raises
    ------
    RuntimeError
        If vectors_dir is None (required for materialization).
    """
    if vectors_dir is None:
        message = "vectors_dir is required to materialize the ID map"
        raise RuntimeError(message)
    h = hashlib.sha256()
    h.update(idmap_parquet.read_bytes())
    for p in sorted(vectors_dir.rglob("*.parquet")):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(p.name.encode("utf-8"))
        h.update(str(st.st_size).encode("ascii"))
        h.update(str(int(st.st_mtime)).encode("ascii"))
    return h.hexdigest()


def refresh_faiss_idmap_materialized(
    conn: duckdb.DuckDBPyConnection,
    *,
    idmap_parquet: str,
    chunks_parquet: str,
) -> IdMapMeta:
    """Materialize FAISS ID map with checksum-based refresh logic.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    idmap_parquet : str
        Path to the FAISS ID map Parquet file containing faiss_row to external_id
        mappings.
    chunks_parquet : str
        Path to the chunks Parquet file (unused, kept for API compatibility).

    Returns
    -------
    IdMapMeta
        Metadata describing the materialized table including checksum, row count,
        and whether a refresh occurred.
    """
    _ = chunks_parquet  # Maintained for compatibility with legacy callers.
    path = Path(idmap_parquet)
    checksum = _parquet_hash(path)
    return _dao_refresh_faiss_idmap_materialized(conn, _idmap_parquet=path, checksum=checksum)


__all__ = [
    "DuckDBCatalog",
    "DuckDBCatalogConfig",
    "IdMapMeta",
    "StructureAnnotations",
    "ensure_faiss_idmap_view",
    "refresh_faiss_idmap_materialized",
    "relation_exists",
]


@dataclass(frozen=True, slots=True)
class DuckDBCatalogConfig:
    """Configuration bundle for constructing DuckDBCatalog instances."""

    db_path: Path
    vectors_dir: Path
    repo_root: Path
    idmap_path: Path
    materialize: bool = False
    log_queries: bool = False
