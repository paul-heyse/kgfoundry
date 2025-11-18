"""Pure DuckDB schema helpers for catalog DDL and queries."""

# The SQL statements in this module only interpolate static relation names;
# dynamic paths are always bound as parameters by the DAO layer.

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class IdMapMeta:
    """Metadata describing a materialized FAISS ID map join."""

    parquet_path: str
    parquet_hash: str
    row_count: int
    refreshed: bool

    @property
    def checksum(self) -> str:
        """Return the checksum (parquet_hash) for the ID map.

        Returns
        -------
        str
            Checksum value matching parquet_hash.
        """
        return self.parquet_hash

    @property
    def rows(self) -> int:
        """Return the row count for the ID map.

        Returns
        -------
        int
            Number of rows matching row_count.
        """
        return self.row_count


@dataclass(frozen=True, slots=True)
class StructMaterializationPlan:
    """SQL bundle describing struct table materialization steps."""

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
    'CREATE OR REPLACE VIEW "chunks" AS SELECT * FROM read_parquet(?)'
)
_SQL_CREATE_EMPTY_CHUNKS_VIEW = 'CREATE OR REPLACE VIEW "chunks" AS ' + EMPTY_CHUNKS_SELECT
_SQL_CREATE_CHUNKS_MATERIALIZED = (
    'CREATE OR REPLACE TABLE "chunks_materialized" AS SELECT * FROM read_parquet(?)'
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
FROM read_parquet(?)
"""
_SQL_CREATE_EMPTY_FAISS_IDMAP_VIEW = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    CAST(NULL AS BIGINT) AS faiss_row,
    CAST(NULL AS BIGINT) AS external_id
WHERE FALSE
"""
_SQL_FAISS_IDMAP_FROM_CHUNK = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    faiss_row,
    chunk_id AS external_id
FROM "faiss_idmap_mat"
"""
_SQL_FAISS_IDMAP_FROM_EXTERNAL = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    faiss_row,
    external_id
FROM "faiss_idmap_mat"
"""
_SQL_FAISS_IDMAP_FROM_NULL = """
CREATE OR REPLACE VIEW "faiss_idmap" AS
SELECT
    faiss_row,
    NULL AS external_id
FROM "faiss_idmap_mat"
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
_SQL_CREATE_IDMAP_MAT = """
CREATE TABLE IF NOT EXISTS "faiss_idmap_mat" AS
SELECT * FROM "v_faiss_join" LIMIT 0
"""
_SQL_CREATE_IDMAP_MAT_META = """
CREATE TABLE IF NOT EXISTS "faiss_idmap_mat_meta" (
    parquet_path TEXT,
    parquet_hash TEXT,
    checksum TEXT,
    row_count BIGINT,
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
INSERT INTO "faiss_idmap_mat_meta"(parquet_path, parquet_hash, checksum, row_count)
VALUES (?, ?, ?, ?)
"""
_COUNTABLE_TABLES: Final[dict[str, str]] = {
    TABLE_FAISS_JOIN_MAT: 'SELECT COUNT(*)::BIGINT FROM "faiss_join_mat"',
    TABLE_FAISS_IDMAP_MAT: 'SELECT COUNT(*)::BIGINT FROM "faiss_idmap_mat"',
}


def sql_create_chunks_view_from_parquet() -> str:
    """Return SQL for creating chunks view from Parquet files.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_CHUNKS_VIEW_FROM_PARQUET


def sql_create_empty_chunks_view() -> str:
    """Return SQL for creating empty chunks view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return _SQL_CREATE_EMPTY_CHUNKS_VIEW


def sql_create_chunks_materialized() -> str:
    """Return SQL for creating materialized chunks table from Parquet.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_CHUNKS_MATERIALIZED


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


def sql_create_faiss_idmap_view() -> str:
    """Return SQL for creating FAISS ID map view from Parquet.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return _SQL_CREATE_FAISS_IDMAP_VIEW


def sql_create_empty_faiss_idmap_view() -> str:
    """Return SQL for creating empty FAISS ID map view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return _SQL_CREATE_EMPTY_FAISS_IDMAP_VIEW


def sql_create_faiss_idmap_from_materialized(column: str | None) -> str:
    """Return SQL for creating FAISS ID map view from the materialized table.

    Parameters
    ----------
    column : str | None
        Column in the materialized table to project as ``external_id``. Supported
        values are ``"chunk_id"`` and ``"external_id"``. Defaults to NULL when
        column is None or unrecognized.

    Returns
    -------
    str
        SQL statement selecting the requested column (or NULL) as ``external_id``.
    """
    if column == "chunk_id":
        return _SQL_FAISS_IDMAP_FROM_CHUNK
    if column == "external_id":
        return _SQL_FAISS_IDMAP_FROM_EXTERNAL
    return _SQL_FAISS_IDMAP_FROM_NULL


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
    """Return SQL for counting rows in a table.

    Parameters
    ----------
    table : str
        Name of the table to count rows from.

    Returns
    -------
    str
        SQL statement returning row count as BIGINT.

    Raises
    ------
    ValueError
        If ``table`` is not part of the supported countable relations.
    """
    try:
        return _COUNTABLE_TABLES[table]
    except KeyError as exc:  # pragma: no cover - defensive guard
        msg = f"Unsupported table for row counting: {table}"
        raise ValueError(msg) from exc


def sql_relation_exists() -> str:
    """Return SQL for checking if a table or view exists.

    Returns
    -------
    str
        SQL statement with placeholder for relation name parameter.
    """
    return """
SELECT 1
FROM (
    SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'
    UNION
    SELECT table_name FROM information_schema.views WHERE table_schema = 'main'
) AS relations
WHERE relations.table_name = ? COLLATE NOCASE
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
