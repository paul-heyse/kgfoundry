"""Pure DuckDB schema helpers for catalog DDL and queries."""

# ruff: noqa: S608
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


def sql_create_chunks_view_from_parquet() -> str:
    """Return SQL for creating chunks view from Parquet files.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return f"CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS SELECT * FROM read_parquet(?)"


def sql_create_empty_chunks_view() -> str:
    """Return SQL for creating empty chunks view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return f"CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS {EMPTY_CHUNKS_SELECT}"


def sql_create_chunks_materialized() -> str:
    """Return SQL for creating materialized chunks table from Parquet.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return f"CREATE OR REPLACE TABLE {TABLE_CHUNKS_MATERIALIZED} AS SELECT * FROM read_parquet(?)"


def sql_create_empty_chunks_materialized() -> str:
    """Return SQL for creating empty materialized chunks table.

    Returns
    -------
    str
        SQL statement creating an empty table with correct schema.
    """
    return f"CREATE OR REPLACE TABLE {TABLE_CHUNKS_MATERIALIZED} AS {EMPTY_CHUNKS_SELECT}"


def sql_create_chunks_view_from_materialized() -> str:
    """Return SQL for creating chunks view from materialized table.

    Returns
    -------
    str
        SQL statement creating a view over the materialized table.
    """
    return f"CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS SELECT * FROM {TABLE_CHUNKS_MATERIALIZED}"


def sql_create_chunks_materialized_index() -> str:
    """Return SQL for creating index on chunks materialized table.

    Returns
    -------
    str
        SQL statement creating an index on the uri column.
    """
    return f"CREATE INDEX IF NOT EXISTS idx_{TABLE_CHUNKS_MATERIALIZED}_uri ON {TABLE_CHUNKS_MATERIALIZED}(uri)"


def sql_create_faiss_idmap_view() -> str:
    """Return SQL for creating FAISS ID map view from Parquet.

    Returns
    -------
    str
        SQL statement with placeholder for Parquet path parameter.
    """
    return f"""
CREATE OR REPLACE VIEW {VIEW_FAISS_IDMAP} AS
SELECT
    faiss_row,
    external_id
FROM read_parquet(?)
"""


def sql_create_empty_faiss_idmap_view() -> str:
    """Return SQL for creating empty FAISS ID map view.

    Returns
    -------
    str
        SQL statement creating an empty view with correct schema.
    """
    return f"""
CREATE OR REPLACE VIEW {VIEW_FAISS_IDMAP} AS
SELECT
    CAST(NULL AS BIGINT) AS faiss_row,
    CAST(NULL AS BIGINT) AS external_id
WHERE FALSE
"""


def sql_create_v_faiss_join() -> str:
    """Return SQL for creating v_faiss_join view.

    Returns
    -------
    str
        SQL statement creating a view joining FAISS ID map with chunks.
    """
    return f"""
CREATE OR REPLACE VIEW {VIEW_V_FAISS_JOIN} AS
SELECT
    f.faiss_row,
    f.external_id AS chunk_id,
    c.*
FROM {VIEW_FAISS_IDMAP} AS f
LEFT JOIN {VIEW_CHUNKS} AS c
  ON c.id = f.external_id
"""


def sql_materialize_v_faiss_join() -> str:
    """Return SQL for materializing v_faiss_join view into table.

    Returns
    -------
    str
        SQL statement creating a table from the view.
    """
    return f"CREATE OR REPLACE TABLE {TABLE_FAISS_JOIN_MAT} AS SELECT * FROM {VIEW_V_FAISS_JOIN}"


def sql_create_idmap_mat() -> str:
    """Return SQL for creating ID map materialized table structure.

    Returns
    -------
    str
        SQL statement creating an empty table with correct schema.
    """
    return f"""
CREATE TABLE IF NOT EXISTS {TABLE_FAISS_IDMAP_MAT} AS
SELECT * FROM {VIEW_V_FAISS_JOIN} LIMIT 0
"""


def sql_create_idmap_mat_meta() -> str:
    """Return SQL for creating ID map metadata table.

    Returns
    -------
    str
        SQL statement creating the metadata table structure.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {TABLE_FAISS_IDMAP_META} (
        parquet_path TEXT,
        parquet_hash TEXT,
        checksum TEXT,
        row_count BIGINT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """


def sql_select_idmap_checksum() -> str:
    """Return SQL for selecting the latest ID map checksum.

    Returns
    -------
    str
        SQL statement selecting the most recent checksum value.
    """
    return f"SELECT checksum FROM {TABLE_FAISS_IDMAP_META} ORDER BY updated_at DESC LIMIT 1"


def sql_delete_idmap_mat() -> str:
    """Return SQL for deleting all rows from ID map materialized table.

    Returns
    -------
    str
        SQL statement deleting all rows from the table.
    """
    return f"DELETE FROM {TABLE_FAISS_IDMAP_MAT}"


def sql_insert_idmap_mat() -> str:
    """Return SQL for inserting rows into ID map materialized table.

    Returns
    -------
    str
        SQL statement inserting rows from the view.
    """
    return f"INSERT INTO {TABLE_FAISS_IDMAP_MAT} SELECT * FROM {VIEW_V_FAISS_JOIN}"


def sql_delete_idmap_meta() -> str:
    """Return SQL for deleting all rows from ID map metadata table.

    Returns
    -------
    str
        SQL statement deleting all rows from the metadata table.
    """
    return f"DELETE FROM {TABLE_FAISS_IDMAP_META}"


def sql_insert_idmap_meta() -> str:
    """Return SQL for inserting row into ID map metadata table.

    Returns
    -------
    str
        SQL statement with placeholders for metadata values.
    """
    return f"""
    INSERT INTO {TABLE_FAISS_IDMAP_META}(parquet_path, parquet_hash, checksum, row_count)
    VALUES (?, ?, ?, ?)
    """


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
    """
    return f"SELECT COUNT(*)::BIGINT FROM {table}"


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
