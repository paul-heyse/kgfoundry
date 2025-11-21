"""Pure DuckDB schema helpers for catalog DDL and queries."""

# The SQL statements in this module only interpolate static relation names;
# dynamic paths are always bound as parameters by the DAO layer.

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class IdMapMeta:
    """Observability summary for FAISS idmap materialization.

    Attributes
    ----------
    checksum : str
        SHA256 checksum of the ID map Parquet file contents.
    rows : int
        Number of rows in the ID map. Must be non-negative.
    refreshed : bool
        Whether the ID map was refreshed (rebuilt) during this operation.
    """

    checksum: str
    rows: int
    refreshed: bool


@dataclass(frozen=True, slots=True)
class StructMaterializationPlan:
    """SQL bundle describing struct table materialization steps.

    Attributes
    ----------
    create_sql : str
        SQL statement for creating the materialized table.
    meta_create_sql : str
        SQL statement for creating the metadata table.
    meta_select_sql : str
        SQL SELECT statement for querying metadata.
    delete_sql : str
        SQL DELETE statement for clearing the materialized table.
    insert_sql : str
        SQL INSERT statement for populating the materialized table.
    meta_delete_sql : str
        SQL DELETE statement for clearing the metadata table.
    meta_insert_sql : str
        SQL INSERT statement for populating the metadata table.
    count_sql : str
        SQL SELECT COUNT(*) statement for counting rows in the materialized table.
    """

    create_sql: str
    meta_create_sql: str
    meta_select_sql: str
    delete_sql: str
    insert_sql: str
    meta_delete_sql: str
    meta_insert_sql: str
    count_sql: str


VIEW_CHUNKS: Final[str] = "chunks"
TABLE_CHUNKS_MATERIALIZED: Final[str] = "chunks_materialized"
VIEW_FAISS_IDMAP: Final[str] = "faiss_idmap"
VIEW_V_FAISS_JOIN: Final[str] = "v_faiss_join"
TABLE_FAISS_JOIN_MAT: Final[str] = "faiss_join_mat"
TABLE_FAISS_IDMAP_MAT: Final[str] = "faiss_idmap_mat"
TABLE_FAISS_IDMAP_META: Final[str] = "faiss_idmap_mat_meta"

EMPTY_CHUNKS_SELECT: Final[str] = """
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

_SQL_CREATE_CHUNKS_VIEW_FROM_PARQUET = (
    'CREATE OR REPLACE VIEW "chunks" AS SELECT * FROM read_parquet({})'
)
_SQL_CREATE_EMPTY_CHUNKS_VIEW = 'CREATE OR REPLACE VIEW "chunks" AS ' + EMPTY_CHUNKS_SELECT
_SQL_CREATE_CHUNKS_MATERIALIZED = (
    'CREATE OR REPLACE TABLE "chunks_materialized" AS SELECT * FROM read_parquet({})'
)
_SQL_CREATE_EMPTY_CHUNKS_MATERIALIZED = (
    'CREATE OR REPLACE TABLE "chunks_materialized" AS ' + EMPTY_CHUNKS_SELECT
)
_SQL_CREATE_CHUNKS_VIEW_FROM_MAT = (
    'CREATE OR REPLACE VIEW "chunks" AS SELECT * FROM "chunks_materialized"'
)
_SQL_CREATE_CHUNKS_MAT_INDEX = (
    'CREATE INDEX IF NOT EXISTS "idx_chunks_materialized_uri" ON "chunks_materialized"(uri)'
)
_SQL_CREATE_FAISS_IDMAP_VIEW = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    faiss_row,
    external_id
FROM read_parquet({})
"""
_SQL_CREATE_EMPTY_FAISS_IDMAP_VIEW = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    CAST(NULL AS BIGINT) AS faiss_row,
    CAST(NULL AS BIGINT) AS external_id
WHERE FALSE
"""
_SQL_CREATE_V_FAISS_JOIN = """
CREATE OR REPLACE VIEW "v_faiss_join" AS
SELECT
    f.faiss_row,
    f.external_id AS chunk_id,
    c.*
FROM "faiss_idmap" AS f
LEFT JOIN "chunks" AS c
  ON c.id = f.external_id
"""
_SQL_MATERIALIZE_V_FAISS_JOIN = (
    'CREATE OR REPLACE TABLE "faiss_join_mat" AS SELECT * FROM "v_faiss_join"'
)
_SQL_CREATE_CHUNK_SYMBOLS_VIEW = """
CREATE OR REPLACE VIEW "v_chunk_symbols" AS
SELECT
    c.id AS chunk_id,
    symbol
FROM chunks AS c,
     LATERAL UNNEST(COALESCE(c.symbols, []::VARCHAR[])) AS t(symbol)
"""
_SQL_CREATE_POOL_COVERAGE_VIEW = """
CREATE OR REPLACE VIEW "v_pool_coverage" AS
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
_SQL_CREATE_POOL_COVERAGE_BASIC_VIEW = """
CREATE OR REPLACE VIEW "v_pool_coverage" AS
SELECT
    pool.*,
    chunks.lang
FROM v_faiss_pool AS pool
LEFT JOIN chunks ON chunks.id = pool.chunk_id
"""
_SQL_CREATE_IDMAP_MAT = """
CREATE TABLE IF NOT EXISTS "faiss_idmap_mat" AS
SELECT * FROM "v_faiss_join" LIMIT 0
"""
_SQL_CREATE_IDMAP_MAT_META = """
CREATE TABLE IF NOT EXISTS "faiss_idmap_mat_meta" (
    checksum   TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
_SQL_SELECT_IDMAP_CHECKSUM = (
    'SELECT checksum FROM "faiss_idmap_mat_meta" ORDER BY updated_at DESC LIMIT 1'
)
_SQL_DELETE_IDMAP_MAT = 'DELETE FROM "faiss_idmap_mat"'
_SQL_INSERT_IDMAP_MAT = 'INSERT INTO "faiss_idmap_mat" SELECT * FROM "v_faiss_join"'
_SQL_DELETE_IDMAP_META = 'DELETE FROM "faiss_idmap_mat_meta"'
_SQL_INSERT_IDMAP_META = """
INSERT INTO "faiss_idmap_mat_meta"(checksum, updated_at)
VALUES (?, CURRENT_TIMESTAMP)
"""
_COUNTABLE_TABLES: Final[dict[str, str]] = {
    TABLE_FAISS_JOIN_MAT: 'SELECT COUNT(*)::BIGINT FROM "faiss_join_mat"',
    TABLE_FAISS_IDMAP_MAT: 'SELECT COUNT(*)::BIGINT FROM "faiss_idmap_mat"',
}

SQL_CREATE_GOID_CROSSWALK_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "goid_crosswalk" AS
SELECT
    g.urn AS goid,
    g.language AS lang,
    CASE
        WHEN g.rel_path LIKE '%.py'
            THEN REPLACE(REGEXP_REPLACE(g.rel_path, '\\.py$', ''), '/', '.')
        ELSE NULL
    END AS module_path,
    g.rel_path AS file_path,
    g.start_line,
    g.end_line,
    gx.scip_symbol,
    g.qualname AS ast_qualname,
    gx.cst_node_id,
    TRY_CAST(gx.chunk_id AS BIGINT) AS chunk_id,
    NULL AS symbol_id,
    COALESCE(g.created_at, CURRENT_TIMESTAMP) AS updated_at
FROM goids AS g
LEFT JOIN goid_xwalk AS gx USING (goid_h128)
"""

SQL_CREATE_CATALOG_CALL_EDGES_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "v_catalog_call_edges" AS
SELECT
    ce.caller_goid_h128,
    ce.callee_goid_h128,
    caller.urn AS caller_goid,
    caller.rel_path AS caller_path,
    caller.language AS caller_lang,
    callee.urn AS callee_goid,
    callee.rel_path AS callee_path,
    callee.language AS callee_lang,
    ce.callsite_path,
    ce.callsite_line,
    ce.callsite_col,
    ce.callsite_path AS file_path,
    ce.callsite_line AS start_line,
    ce.callsite_line AS end_line,
    ce.language,
    ce.kind,
    ce.resolved_via,
    ce.confidence,
    ce.callee_goid_h128 IS NOT NULL AS resolved,
    CURRENT_TIMESTAMP AS updated_at
FROM call_edges AS ce
LEFT JOIN goids AS caller
  ON caller.goid_h128 = ce.caller_goid_h128
LEFT JOIN goids AS callee
  ON callee.goid_h128 = ce.callee_goid_h128
"""

SQL_CREATE_CATALOG_CFG_BLOCKS_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "v_catalog_cfg_blocks" AS
SELECT
    go.urn AS function_goid,
    go.goid_h128 AS function_goid_h128,
    cb.block_idx,
    go.urn || ':block' || CAST(cb.block_idx AS VARCHAR) AS block_id,
    cb.kind || ':' || CAST(cb.block_idx AS VARCHAR) AS label,
    go.rel_path AS file_path,
    cb.start_line,
    cb.end_line,
    cb.kind,
    cb.stmts_json,
    cb.in_degree,
    cb.out_degree
FROM cfg_blocks AS cb
LEFT JOIN goids AS go
  ON go.goid_h128 = cb.function_goid_h128
"""

SQL_CREATE_CATALOG_CFG_EDGES_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "v_catalog_cfg_edges" AS
SELECT
    go.urn AS function_goid,
    go.goid_h128 AS function_goid_h128,
    ce.src_block_idx,
    ce.dst_block_idx,
    go.urn || ':block' || CAST(ce.src_block_idx AS VARCHAR) AS src,
    go.urn || ':block' || CAST(ce.dst_block_idx AS VARCHAR) AS dst,
    ce.edge_type AS label,
    ce.edge_type,
    ce.cond_json
FROM cfg_edges AS ce
LEFT JOIN goids AS go
  ON go.goid_h128 = ce.function_goid_h128
"""

SQL_CREATE_CATALOG_DFG_NODES_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "v_catalog_dfg_nodes" AS
WITH function_meta AS (
    SELECT
        goid_h128,
        urn AS function_goid,
        rel_path AS file_path
    FROM goids
),
block_spans AS (
    SELECT
        function_goid_h128,
        block_idx,
        start_line,
        end_line
    FROM cfg_blocks
)
SELECT DISTINCT
    meta.function_goid,
    meta.goid_h128 AS function_goid_h128,
    meta.file_path,
    de.src_block_idx AS block_idx,
    block.start_line,
    block.end_line,
    de.src_symbol AS symbol,
    meta.function_goid || ':b' || CAST(de.src_block_idx AS VARCHAR) ||
        ':' || COALESCE(de.src_symbol, 'None') ||
        ':def' AS node_id,
    'def' AS kind
FROM dfg_edges AS de
JOIN function_meta AS meta
  ON meta.goid_h128 = de.function_goid_h128
LEFT JOIN block_spans AS block
  ON block.function_goid_h128 = de.function_goid_h128
 AND block.block_idx = de.src_block_idx
UNION
SELECT DISTINCT
    meta.function_goid,
    meta.goid_h128 AS function_goid_h128,
    meta.file_path,
    de.dst_block_idx AS block_idx,
    block.start_line,
    block.end_line,
    de.dst_symbol AS symbol,
    meta.function_goid || ':b' || CAST(de.dst_block_idx AS VARCHAR) ||
        ':' || COALESCE(de.dst_symbol, 'None') ||
        CASE WHEN de.via_phi THEN ':phi' ELSE ':use' END AS node_id,
    CASE WHEN de.via_phi THEN 'phi' ELSE 'use' END AS kind
FROM dfg_edges AS de
JOIN function_meta AS meta
  ON meta.goid_h128 = de.function_goid_h128
LEFT JOIN block_spans AS block
  ON block.function_goid_h128 = de.function_goid_h128
 AND block.block_idx = de.dst_block_idx
"""

SQL_CREATE_CATALOG_DFG_EDGES_VIEW: Final[str] = """
CREATE VIEW IF NOT EXISTS "v_catalog_dfg_edges" AS
SELECT
    meta.function_goid,
    meta.goid_h128 AS function_goid_h128,
    meta.function_goid || ':b' || CAST(de.src_block_idx AS VARCHAR) ||
        ':' || COALESCE(de.src_symbol, 'None') ||
        ':def' AS src,
    meta.function_goid || ':b' || CAST(de.dst_block_idx AS VARCHAR) ||
        ':' || COALESCE(de.dst_symbol, 'None') ||
        CASE WHEN de.via_phi THEN ':phi' ELSE ':use' END AS dst,
    de.use_kind AS label
FROM dfg_edges AS de
JOIN (
    SELECT goid_h128, urn AS function_goid
    FROM goids
) AS meta
  ON meta.goid_h128 = de.function_goid_h128
"""

SQL_CREATE_GOIDS_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "goids" (
    goid_h128   HUGEINT PRIMARY KEY,
    urn         VARCHAR NOT NULL,
    repo        VARCHAR NOT NULL,
    commit      VARCHAR NOT NULL,
    rel_path    VARCHAR NOT NULL,
    language    VARCHAR NOT NULL,
    kind        VARCHAR NOT NULL,
    qualname    VARCHAR,
    start_line  INTEGER,
    end_line    INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

SQL_CREATE_GOID_XWALK_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "goid_xwalk" (
    goid_h128      HUGEINT NOT NULL REFERENCES goids(goid_h128),
    scip_symbol    VARCHAR,
    chunk_id       VARCHAR,
    chunk_row_id   BIGINT,
    cst_node_id    VARCHAR,
    ast_node_type  VARCHAR,
    git_blob_sha   VARCHAR,
    git_commit_sha VARCHAR,
    evidence_json  JSON,
    UNIQUE (goid_h128, scip_symbol, chunk_id)
)
"""

SQL_CREATE_V_GOID_BY_SYMBOL: Final[str] = """
CREATE OR REPLACE VIEW "v_goid_by_symbol" AS
SELECT go.*, gx.scip_symbol
FROM "goids" AS go
LEFT JOIN "goid_xwalk" AS gx USING (goid_h128)
WHERE gx.scip_symbol IS NOT NULL
"""

SQL_INDEX_GOIDS_PATH_KIND: Final[str] = """
CREATE INDEX IF NOT EXISTS "idx_goids_path_kind" ON "goids"(rel_path, kind)
"""

SQL_INDEX_GOID_XWALK_SYMBOL: Final[str] = """
CREATE INDEX IF NOT EXISTS "idx_goid_xwalk_symbol" ON "goid_xwalk"(scip_symbol)
"""

SQL_CREATE_CALL_NODES_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "call_nodes" (
    goid_h128 HUGEINT PRIMARY KEY,
    language  VARCHAR NOT NULL,
    kind      VARCHAR NOT NULL,
    arity     INTEGER,
    is_public BOOLEAN,
    rel_path  VARCHAR NOT NULL
)
"""

SQL_CREATE_CALL_EDGES_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "call_edges" (
    caller_goid_h128 HUGEINT NOT NULL REFERENCES call_nodes(goid_h128),
    callee_goid_h128 HUGEINT,
    callsite_path    VARCHAR NOT NULL,
    callsite_line    INTEGER,
    callsite_col     INTEGER,
    language         VARCHAR NOT NULL,
    kind             VARCHAR NOT NULL,
    resolved_via     VARCHAR NOT NULL,
    confidence       DOUBLE NOT NULL,
    evidence_json    JSON,
    PRIMARY KEY (caller_goid_h128, callsite_path, callsite_line, callsite_col)
)
"""

SQL_INDEX_CALL_EDGES_CALLEE: Final[str] = """
CREATE INDEX IF NOT EXISTS "idx_call_edges_callee" ON "call_edges"(callee_goid_h128)
"""

SQL_CREATE_CFG_BLOCKS_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "cfg_blocks" (
    function_goid_h128 HUGEINT NOT NULL,
    block_idx          INTEGER NOT NULL,
    kind               VARCHAR NOT NULL,
    start_line         INTEGER,
    end_line           INTEGER,
    stmts_json         JSON,
    in_degree          INTEGER,
    out_degree         INTEGER,
    PRIMARY KEY (function_goid_h128, block_idx)
)
"""

SQL_CREATE_CFG_EDGES_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "cfg_edges" (
    function_goid_h128 HUGEINT NOT NULL,
    src_block_idx      INTEGER NOT NULL,
    dst_block_idx      INTEGER NOT NULL,
    edge_type          VARCHAR NOT NULL,
    cond_json          JSON,
    PRIMARY KEY (function_goid_h128, src_block_idx, dst_block_idx)
)
"""

SQL_CREATE_DFG_EDGES_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS "dfg_edges" (
    function_goid_h128 HUGEINT NOT NULL,
    src_block_idx      INTEGER NOT NULL,
    dst_block_idx      INTEGER NOT NULL,
    src_symbol         VARCHAR NOT NULL,
    dst_symbol         VARCHAR NOT NULL,
    via_phi            BOOLEAN,
    use_kind           VARCHAR NOT NULL,
    PRIMARY KEY (
        function_goid_h128,
        src_block_idx,
        dst_block_idx,
        src_symbol,
        dst_symbol,
        use_kind
    )
)
"""

SQL_INDEX_CFG_BLOCKS_FUNCTION: Final[str] = """
CREATE INDEX IF NOT EXISTS "idx_cfg_blocks_function" ON "cfg_blocks"(function_goid_h128)
"""

SQL_INDEX_DFG_SYMBOL: Final[str] = """
CREATE INDEX IF NOT EXISTS "idx_dfg_symbol" ON "dfg_edges"(function_goid_h128, dst_symbol)
"""


def sql_create_chunks_view_from_parquet(parquet_literal: str) -> str:
    """Return SQL for creating chunks view from Parquet files.

    Parameters
    ----------
    parquet_literal : str
        SQL-quoted Parquet file path literal to use in the CREATE VIEW statement.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_CHUNKS_VIEW_FROM_PARQUET.format(parquet_literal)


def sql_create_empty_chunks_view() -> str:
    """Return SQL for creating empty chunks view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return _SQL_CREATE_EMPTY_CHUNKS_VIEW


def sql_create_chunks_materialized(parquet_literal: str) -> str:
    """Return SQL for creating materialized chunks table from Parquet.

    Parameters
    ----------
    parquet_literal : str
        SQL-quoted Parquet file path literal to use in the CREATE TABLE statement.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_CHUNKS_MATERIALIZED.format(parquet_literal)


def sql_create_empty_chunks_materialized() -> str:
    """Return SQL for creating empty materialized chunks table.

    Returns
    -------
    str
        SQL statement creating an empty table with correct schema.
    """
    return _SQL_CREATE_EMPTY_CHUNKS_MATERIALIZED


def sql_create_chunks_view_from_materialized() -> str:
    """Return SQL for creating chunks view from materialized table.

    Returns
    -------
    str
        SQL statement creating a view over the materialized table.
    """
    return _SQL_CREATE_CHUNKS_VIEW_FROM_MAT


def sql_create_chunks_materialized_index() -> str:
    """Return SQL for creating index on chunks materialized table.

    Returns
    -------
    str
        SQL statement creating an index on the uri column.
    """
    return _SQL_CREATE_CHUNKS_MAT_INDEX


def sql_create_faiss_idmap_view(parquet_literal: str) -> str:
    """Return SQL for creating FAISS ID map view from Parquet.

    Parameters
    ----------
    parquet_literal : str
        SQL-quoted Parquet file path literal to use in the CREATE VIEW statement.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_FAISS_IDMAP_VIEW.format(parquet_literal)


def sql_create_empty_faiss_idmap_view() -> str:
    """Return SQL for creating empty FAISS ID map view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return _SQL_CREATE_EMPTY_FAISS_IDMAP_VIEW


def sql_create_v_faiss_join() -> str:
    """Return SQL for creating v_faiss_join view.

    Returns
    -------
    str
        SQL statement creating a view joining FAISS ID map with chunks.
    """
    return _SQL_CREATE_V_FAISS_JOIN


def sql_materialize_v_faiss_join() -> str:
    """Return SQL for materializing v_faiss_join view into table.

    Returns
    -------
    str
        SQL statement creating a table from the view.
    """
    return _SQL_MATERIALIZE_V_FAISS_JOIN


def sql_create_chunk_symbols_view() -> str:
    """Return SQL for creating v_chunk_symbols view.

    Returns
    -------
    str
        SQL statement creating the chunk symbol view.
    """
    return _SQL_CREATE_CHUNK_SYMBOLS_VIEW


def sql_create_pool_coverage_view(*, include_modules: bool) -> str:
    """Return SQL for creating v_pool_coverage with optional module joins.

    Parameters
    ----------
    include_modules : bool
        When ``True``, joins against modules for repo metadata.

    Returns
    -------
    str
        SQL statement creating the pool coverage view.
    """
    if include_modules:
        return _SQL_CREATE_POOL_COVERAGE_VIEW
    return _SQL_CREATE_POOL_COVERAGE_BASIC_VIEW


def sql_create_idmap_mat() -> str:
    """Return SQL for creating ID map materialized table structure.

    Returns
    -------
    str
        SQL statement creating an empty table with correct schema.
    """
    return _SQL_CREATE_IDMAP_MAT


def sql_create_idmap_mat_meta() -> str:
    """Return SQL for creating ID map metadata table.

    Returns
    -------
    str
        SQL statement creating the metadata table structure.
    """
    return _SQL_CREATE_IDMAP_MAT_META


def sql_select_idmap_checksum() -> str:
    """Return SQL for selecting the latest ID map checksum.

    Returns
    -------
    str
        SQL statement selecting the most recent checksum value.
    """
    return _SQL_SELECT_IDMAP_CHECKSUM


def sql_delete_idmap_mat() -> str:
    """Return SQL for deleting all rows from ID map materialized table.

    Returns
    -------
    str
        SQL statement deleting all rows from the table.
    """
    return _SQL_DELETE_IDMAP_MAT


def sql_insert_idmap_mat() -> str:
    """Return SQL for inserting rows into ID map materialized table.

    Returns
    -------
    str
        SQL statement inserting rows from the view.
    """
    return _SQL_INSERT_IDMAP_MAT


def sql_delete_idmap_meta() -> str:
    """Return SQL for deleting all rows from ID map metadata table.

    Returns
    -------
    str
        SQL statement deleting all rows from the metadata table.
    """
    return _SQL_DELETE_IDMAP_META


def sql_insert_idmap_meta() -> str:
    """Return SQL for inserting row into ID map metadata table.

    Returns
    -------
    str
        SQL statement with placeholders for metadata values.
    """
    return _SQL_INSERT_IDMAP_META


def sql_count(table: str) -> str:
    """Return SQL for counting rows in supported relations.

    Parameters
    ----------
    table : str
        Name of the relation to count.

    Returns
    -------
    str
        SQL statement returning the row count for ``table``.

    Raises
    ------
    ValueError
        If ``table`` is not part of the supported mapping.
    """
    try:
        return _COUNTABLE_TABLES[table]
    except KeyError as exc:  # pragma: no cover - defensive
        msg = f"Unsupported table for row counting: {table}"
        raise ValueError(msg) from exc


def sql_relation_exists() -> str:
    """Return SQL for checking relation existence.

    Returns
    -------
    str
        SQL statement checking DuckDB information_schema for a relation.
    """
    return """
    SELECT 1 FROM information_schema.tables
    WHERE table_name = ? COLLATE NOCASE
       OR table_name = REPLACE(?, '"', '')
    LIMIT 1
    """


STRUCT_PLANS: dict[str, StructMaterializationPlan] = {
    "modules_mat": StructMaterializationPlan(
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
        count_sql="SELECT COUNT(*)::BIGINT FROM modules_mat",
    ),
}
