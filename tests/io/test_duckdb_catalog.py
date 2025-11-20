"""Tests covering the DuckDB catalog refactor."""

from pathlib import Path

import duckdb
import pytest
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions

from tests._helpers import assertions


def _write_parquet(path: Path, select_sql: str) -> None:
    """Write parquet file from SQL SELECT statement.

    Parameters
    ----------
    path : Path
        Output parquet file path.
    select_sql : str
        SQL SELECT statement to execute.
    """
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute("DROP TABLE IF EXISTS tmp")
        relation = conn.sql(select_sql)
        relation.create("tmp")
        conn.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        conn.close()


def _write_chunk_parquet(path: Path) -> None:
    """Write test chunk parquet file.

    Parameters
    ----------
    path : Path
        Output parquet file path.
    """
    _write_parquet(
        path,
        """
        SELECT
            1::BIGINT AS id,
            'src/main.py'::VARCHAR AS uri,
            0::INTEGER AS start_line,
            1::INTEGER AS end_line,
            0::BIGINT AS start_byte,
            12::BIGINT AS end_byte,
            'preview'::VARCHAR AS preview,
            'content'::VARCHAR AS content,
            'python'::VARCHAR AS lang,
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )


def _write_idmap_parquet(path: Path) -> None:
    """Write test ID map parquet file.

    Parameters
    ----------
    path : Path
        Output parquet file path.
    """
    _write_parquet(
        path,
        """
        SELECT
            0::BIGINT AS faiss_row,
            1::BIGINT AS external_id
        """,
    )


def _build_catalog(tmp_path: Path) -> tuple[DuckDBCatalog, Path]:
    """Build test catalog with chunk and ID map data.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory.

    Returns
    -------
    tuple[DuckDBCatalog, Path]
        Tuple of catalog instance and ID map parquet path.
    """
    data_root = tmp_path / "data"
    vectors_dir = data_root / "vectors"
    vectors_dir.mkdir(parents=True)
    chunk_parquet = vectors_dir / "chunks.parquet"
    _write_chunk_parquet(chunk_parquet)
    db_path = tmp_path / "catalog.duckdb"
    options = DuckDBCatalogOptions()
    catalog = DuckDBCatalog(db_path, vectors_dir, options=options)
    idmap_parquet = tmp_path / "faiss_idmap.parquet"
    _write_idmap_parquet(idmap_parquet)
    return catalog, idmap_parquet


def _fetch_single_value(conn: duckdb.DuckDBPyConnection, sql: str, *, reason: str) -> int:
    """Fetch single integer value from query or fail test.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection.
    sql : str
        SQL query to execute.
    reason : str
        Failure reason if query returns no rows.

    Returns
    -------
    int
        Integer value from first column of first row.

    Raises
    ------
    pytest.fail
        If query returns no rows.
    """
    row = conn.execute(sql).fetchone()
    if row is None:
        pytest.fail(f"{reason}: query returned no rows")
    return int(row[0])


def test_register_idmap_creates_views(tmp_path: Path) -> None:
    """Verify that registering an ID map creates required views without materialization."""
    catalog, idmap_parquet = _build_catalog(tmp_path)
    stats = catalog.register_idmap_parquet(idmap_parquet, materialize=False)
    assertions.expect_equal(stats["rows"], 1)
    assertions.expect_true(stats["refreshed"])

    with catalog.connection() as conn:
        count = _fetch_single_value(
            conn, "SELECT COUNT(*) FROM faiss_idmap", reason="faiss_idmap count"
        )
        assertions.expect_equal(count, 1)
        join_count = _fetch_single_value(
            conn, "SELECT COUNT(*) FROM v_faiss_join", reason="v_faiss_join count"
        )
        assertions.expect_equal(join_count, 1)


def test_register_idmap_materializes_join(tmp_path: Path) -> None:
    """Verify that registering an ID map with materialization creates materialized join view."""
    catalog, idmap_parquet = _build_catalog(tmp_path)
    first = catalog.register_idmap_parquet(idmap_parquet, materialize=True)
    assertions.expect_equal(first["rows"], 1)
    assertions.expect_true(first["refreshed"])

    with catalog.connection() as conn:
        join_count = _fetch_single_value(
            conn,
            "SELECT COUNT(*) FROM faiss_join_mat",
            reason="faiss_join_mat count",
        )
        assertions.expect_equal(join_count, 1)

    second = catalog.register_idmap_parquet(idmap_parquet, materialize=True)
    assertions.expect_equal(second["rows"], 1)
    assertions.expect_false(second["refreshed"])
