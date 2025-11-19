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
