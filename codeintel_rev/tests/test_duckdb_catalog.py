"""Tests covering DuckDB catalog helpers and semantic search hydration."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.adapters import semantic

MATCHING_CHUNK_ID = 42
MATCHING_PREVIEW = "semantic chunk"


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def _write_chunk_parquet(parquet_path: Path) -> None:
    conn = duckdb.connect()
    try:
        conn.execute(
            """
            CREATE TABLE chunks AS
            SELECT * FROM (VALUES
                (
                    1,
                    'src/example.py',
                    10,
                    20,
                    0,
                    42,
                    'Example preview'
                )
            ) AS t(id, uri, start_line, end_line, start_byte, end_byte, preview)
            """
        )
        conn.execute(
            "COPY chunks TO ? (FORMAT PARQUET)",
            [str(parquet_path)],
        )
    finally:
        conn.close()


def _write_chunk_parquet_with_embedding(parquet_path: Path, vec_dim: int) -> None:
    """Write a parquet file containing an embedding column for tests.

    Parameters
    ----------
    parquet_path : Path
        Destination parquet path.
    vec_dim : int
        Embedding dimension.

    """
    values = ", ".join(f"{0.1 * (i + 1):.1f}" for i in range(vec_dim))
    conn = duckdb.connect()
    try:
        conn.execute(
            f"""
            CREATE TABLE chunks AS
            SELECT
                1 AS id,
                'src/example.py' AS uri,
                0 AS start_line,
                0 AS end_line,
                0 AS start_byte,
                10 AS end_byte,
                'Example preview' AS preview,
                LIST_VALUE({values})::FLOAT[] AS embedding
            """
        )
        conn.execute(
            "COPY chunks TO ? (FORMAT PARQUET)",
            [str(parquet_path)],
        )
    finally:
        conn.close()


def _write_chunks_parquet(path: Path) -> None:
    connection = duckdb.connect(database=":memory:")
    connection.execute("CREATE TABLE tmp (id INTEGER, uri VARCHAR, text VARCHAR)")
    connection.executemany(
        "INSERT INTO tmp VALUES (?, ?, ?)",
        [
            (2, "example.py", "second"),
            (1, "example.py", "first"),
            (3, "other.py", "other"),
        ],
    )
    connection.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()


def _table_exists(db_path: Path, table_name: str) -> bool:
    connection = duckdb.connect(str(db_path))
    try:
        return (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name = ?
                """,
                [table_name],
            ).fetchone()[0]
            > 0
        )
    finally:
        connection.close()


def _index_exists(db_path: Path, index_name: str) -> bool:
    connection = duckdb.connect(str(db_path))
    try:
        return (
            connection.execute(
                "SELECT COUNT(*) FROM pragma_show_indexes() WHERE name = ?",
                [index_name],
            ).fetchone()[0]
            > 0
        )
    finally:
        connection.close()


class FakeVLLMClient:
    """Record embedding requests made during semantic search."""

    def __init__(self, _config: object) -> None:
        self.calls: list[str] = []

    def embed_single(self, query: str) -> list[float]:
        """Return a deterministic embedding vector for *query*.

        Parameters
        ----------
        query : str
            Query text to embed.

        Returns
        -------
        list[float]
            Mock embedding vector ``[0.1, 0.2, 0.3]``.
        """
        self.calls.append(query)
        return [0.1, 0.2, 0.3]


class FakeFAISSManager:
    """Provide deterministic FAISS results for tests."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.gpu_disabled_reason: str | None = None
        self.gpu_index = None

    @staticmethod
    def load_cpu_index() -> None:  # pragma: no cover - trivial shim
        """Pretend to load the FAISS CPU index."""
        return

    @staticmethod
    def clone_to_gpu() -> bool:  # pragma: no cover - trivial shim
        """Report that GPU cloning succeeded.

        Returns
        -------
        bool
            Always ``True`` to indicate success.
        """
        return True

    @staticmethod
    def search(_query_vec: np.ndarray, *, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Return ``k`` mock search results.

        Parameters
        ----------
        _query_vec : np.ndarray
            Query vector (unused in mock).
        k : int
            Number of results to return.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Pair of distances and chunk identifiers.
        """
        _ = k
        return (
            np.array([[0.123]], dtype=np.float32),
            np.array([[MATCHING_CHUNK_ID]], dtype=np.int64),
        )


class RecordingCatalog:
    """Capture hydrated chunk identifiers for verification."""

    def __init__(self) -> None:
        """Initialise the in-memory catalog."""
        self.queries: list[list[int]] = []

    def query_by_ids(self, ids: list[int]) -> list[dict]:
        """Return chunk metadata for any matching identifiers.

        Parameters
        ----------
        ids : list[int]
            Chunk identifiers to query.

        Returns
        -------
        list[dict]
            Chunk metadata records matching the provided identifiers.
        """
        self.queries.append(list(ids))
        if MATCHING_CHUNK_ID in ids:
            return [
                {
                    "id": MATCHING_CHUNK_ID,
                    "uri": "src/demo.py",
                    "start_line": 1,
                    "end_line": 5,
                    "preview": MATCHING_PREVIEW,
                }
            ]
        return []


class StubContext:
    """Stub service context yielding deterministic dependencies."""

    def __init__(self) -> None:
        """Initialise stubbed dependencies for semantic search tests."""
        self.faiss_manager = FakeFAISSManager()
        self.vllm_client = FakeVLLMClient(SimpleNamespace())
        self.settings = SimpleNamespace()
        self._limits: list[str] = []
        self._error: str | None = None
        self.catalog = RecordingCatalog()

    def ensure_faiss_ready(self) -> tuple[bool, list[str], str | None]:
        """Return readiness tuple.

        Returns
        -------
        tuple[bool, list[str], str | None]
            Tuple of (ready, limits, error).
        """
        return True, list(self._limits), self._error

    @contextmanager
    def open_catalog(self) -> Iterator[RecordingCatalog]:
        """Yield stub catalog.

        Yields
        ------
        RecordingCatalog
            Stub catalog instance.
        """
        yield self.catalog


def test_open_creates_empty_view(tmp_path: Path) -> None:
    """Ensure the catalog initialises when no vectors are present."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog_path = tmp_path / "catalog.duckdb"

    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    catalog.open()
    try:
        _expect(
            condition=catalog.count_chunks() == 0,
            message="Expected zero chunks for empty catalog",
        )
        _expect(
            condition=catalog.query_by_ids([]) == [],
            message="Empty query should return empty results",
        )
    finally:
        catalog.close()


def test_get_chunk_by_id_returns_single_record(tmp_path: Path) -> None:
    """Ensure DuckDBCatalog returns hydrated chunk metadata."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunk_parquet(parquet_path)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir) as catalog:
        chunk = catalog.get_chunk_by_id(1)
        _expect(condition=chunk is not None, message="Expected chunk to be found")
        if chunk is not None:
            _expect(
                condition=chunk["uri"] == "src/example.py",
                message="Unexpected URI for chunk",
            )
            _expect(
                condition=chunk["preview"] == "Example preview",
                message="Unexpected preview text",
            )
        records = catalog.query_by_ids([1])
        _expect(condition=len(records) == 1, message="Expected one record from query_by_ids")
        _expect(
            condition=records[0]["uri"] == "src/example.py",
            message="Unexpected URI from query_by_ids",
        )
        _expect(
            condition=catalog.get_chunk_by_id(9999) is None,
            message="Expected None for missing chunk",
        )


def test_get_embeddings_by_ids_returns_correct_shapes(tmp_path: Path) -> None:
    """Ensure embedding queries return matrices with consistent shape."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunk_parquet_with_embedding(parquet_path, vec_dim=3)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir) as catalog:
        empty_matrix = catalog.get_embeddings_by_ids([])
        _expect(condition=empty_matrix.shape == (0, 3), message="Expected (0, 3) for empty query")

        result = catalog.get_embeddings_by_ids([1])
        _expect(condition=result.shape == (1, 3), message="Expected single embedding row")
        _expect(
            condition=np.allclose(result[0], [0.1, 0.2, 0.3]), message="Unexpected embedding values"
        )

        missing = catalog.get_embeddings_by_ids([999])
        _expect(condition=missing.shape == (0, 3), message="Missing IDs should return empty matrix")


@pytest.mark.asyncio
async def test_semantic_search_handles_chunk_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify semantic search hydrates chunk metadata using DuckDB."""
    # Type ignore: SimpleNamespace used as module mock in tests
    monkeypatch.setitem(sys.modules, "faiss", SimpleNamespace())  # type: ignore[arg-type]
    _ = tmp_path

    context = StubContext()

    monkeypatch.setattr(semantic, "get_service_context", lambda: context)

    result = await semantic.semantic_search("test query", limit=1)

    findings = result.get("findings", [])
    _expect(condition=bool(findings), message="Expected findings to be non-empty")
    finding = findings[0]
    _expect(
        condition=finding.get("snippet") == MATCHING_PREVIEW,
        message="Unexpected snippet content",
    )
    _expect(
        condition=finding.get("location", {}).get("uri") == "src/demo.py",
        message="Unexpected hydrated URI",
    )
    _expect(
        condition=context.catalog.queries == [[MATCHING_CHUNK_ID]],
        message="Unexpected chunk IDs during hydration",
    )


def test_query_by_filters_returns_correct_results(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunk_parquet(parquet_path)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir) as catalog:
        results = catalog.query_by_filters([1], include_globs=["src/config_file.py"])
        assert len(results) == 1
        assert results[0]["uri"] == "src/config_file.py"


def test_query_by_filters_handles_literal_underscore(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    catalog.conn = duckdb.connect(database=":memory:")
    catalog.conn.execute(
        """
        CREATE OR REPLACE VIEW chunks AS
        SELECT * FROM (
            SELECT
                1::BIGINT AS id,
                'src/config_file.py'::VARCHAR AS uri,
                0::INTEGER AS start_line,
                1::INTEGER AS end_line,
                0::BIGINT AS start_byte,
                10::BIGINT AS end_byte,
                'underscore file'::VARCHAR AS preview,
                [0.1, 0.2]::FLOAT[] AS embedding
        )
        """
    )

    results = catalog.query_by_filters([1], include_globs=["src/config_file.py"])
    assert len(results) == 1
    assert results[0]["uri"] == "src/config_file.py"


def test_open_materialize_creates_table_and_index(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunks_parquet(parquet_path)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assert catalog.count_chunks() == 3

    assert _table_exists(catalog_path, "chunks_materialized") is True
    assert _index_exists(catalog_path, "idx_chunks_materialized_uri") is True

    connection = duckdb.connect(str(catalog_path))
    try:
        row_count = connection.execute("SELECT COUNT(*) FROM chunks_materialized").fetchone()[0]
    finally:
        connection.close()

    assert row_count == 3


def test_materialize_creates_empty_table_when_parquet_missing(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assert catalog.count_chunks() == 0

    assert _table_exists(catalog_path, "chunks_materialized") is True
    assert _index_exists(catalog_path, "idx_chunks_materialized_uri") is True
