"""Performance benchmarks for scope filtering operations.

This module benchmarks the performance overhead of scope filtering compared to
baseline queries without filtering. Tests verify that filtering adds <5ms overhead
for typical query sizes (1000 chunks).

Benchmarks:
- Baseline: query_by_ids (no filtering)
- Language filter: query_by_filters with languages=["python"]
- Path globs: query_by_filters with include_globs=["src/**"]
- Combined filters: query_by_filters with both language and path filters

All benchmarks use pytest-benchmark plugin for accurate timing and reporting.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import duckdb
import pytest
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager

# Number of chunks to create for benchmark
# Reduced from 100K to 10K for faster fixture setup while still providing meaningful benchmarks
BENCHMARK_CHUNK_COUNT = 10_000

# Number of chunks to query in each benchmark
QUERY_CHUNK_COUNT = 1000

# Performance threshold: filtering overhead should be <5ms
MAX_FILTER_OVERHEAD_MS = 5.0


def _generate_chunk_uri(
    chunk_id: int,
    languages: list[str],
    directories: list[str],
    extensions: dict[str, list[str]],
) -> str:
    """Generate a URI for a chunk based on its ID.

    Parameters
    ----------
    chunk_id : int
        Chunk identifier.
    languages : list[str]
        Available languages.
    directories : list[str]
        Available directories.
    extensions : dict[str, list[str]]
        Language to extension mapping.

    Returns
    -------
    str
        Generated URI for the chunk.
    """
    lang = languages[chunk_id % len(languages)]
    directory = directories[chunk_id % len(directories)]
    ext = extensions[lang][chunk_id % len(extensions[lang])]

    # Create nested paths occasionally
    if chunk_id % 10 == 0:
        return f"{directory}/nested/deep/file{chunk_id}{ext}"
    if chunk_id % 5 == 0:
        return f"{directory}/subdir/file{chunk_id}{ext}"
    return f"{directory}/file{chunk_id}{ext}"


def _generate_chunk_data(
    chunk_id: int, uri: str
) -> tuple[int, str, int, int, int, int, str, list[float]]:
    """Generate chunk data tuple for a given chunk ID and URI.

    Parameters
    ----------
    chunk_id : int
        Chunk identifier.
    uri : str
        Chunk URI.

    Returns
    -------
    tuple[int, str, int, int, int, int, str, list[float]]
        Chunk data tuple (id, uri, start_line, end_line, start_byte, end_byte, preview, embedding).
    """
    start_line = (chunk_id % 100) + 1
    end_line = start_line + 10
    start_byte = chunk_id * 100
    end_byte = start_byte + 500
    preview = f"Code chunk {chunk_id} in {uri}"
    # Use a simpler embedding representation for performance
    # Generate smaller embedding array (100 dims) for faster insertion
    # Real embeddings are 2560-dim, but for benchmarks we only need realistic data size
    embedding = [
        float(x % 100) / 100.0 for x in range(100)
    ]  # 100-dim embedding for speed

    return (
        chunk_id,
        uri,
        start_line,
        end_line,
        start_byte,
        end_byte,
        preview,
        embedding,
    )


@pytest.fixture(scope="session")
def benchmark_catalog(tmp_path_factory) -> DuckDBCatalog:
    """Create a DuckDB catalog with 100K chunks for benchmarking.

    Creates a catalog with diverse URIs representing various languages and
    directory structures to simulate real-world codebase indexing.

    Parameters
    ----------
    tmp_path_factory : pytest.TempPathFactory
        Pytest fixture factory for creating temporary directories.

    Returns
    -------
    DuckDBCatalog
        Catalog instance with 10K chunks loaded.

    Notes
    -----
    This fixture creates a large dataset (10K chunks) which may take several
    seconds to initialize. The fixture is session-scoped to avoid recreating
    it for each benchmark test.
    """
    # Use session-scoped tmp_path for shared fixture
    tmp_path = tmp_path_factory.mktemp("benchmark")
    db_path = tmp_path / "benchmark.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog = DuckDBCatalog(db_path, vectors_dir)

    # Generate diverse URIs for benchmarking
    # Mix of languages: Python, TypeScript, JavaScript, Rust, Go, Java, etc.
    # Mix of directories: src/, tests/, lib/, docs/, etc.
    languages = ["python", "typescript", "javascript", "rust", "go", "java"]
    directories = ["src", "tests", "lib", "docs", "scripts", "config"]
    extensions = {
        "python": [".py", ".pyi"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx"],
        "rust": [".rs"],
        "go": [".go"],
        "java": [".java"],
    }

    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE chunks (
                id BIGINT,
                uri VARCHAR,
                start_line INTEGER,
                end_line INTEGER,
                start_byte BIGINT,
                end_byte BIGINT,
                preview VARCHAR,
                embedding FLOAT[]
            )
            """
        )

        # Generate and insert chunks in batches for performance
        batch_size = 10_000
        chunk_id = 1

        for batch_start in range(0, BENCHMARK_CHUNK_COUNT, batch_size):
            batch_end = min(batch_start + batch_size, BENCHMARK_CHUNK_COUNT)
            batch_data: list[tuple[int, str, int, int, int, int, str, list[float]]] = []

            for _ in range(batch_start, batch_end):
                uri = _generate_chunk_uri(chunk_id, languages, directories, extensions)
                chunk_data = _generate_chunk_data(chunk_id, uri)
                batch_data.append(chunk_data)
                chunk_id += 1

            connection.executemany(
                """
                INSERT INTO chunks (id, uri, start_line, end_line, start_byte, end_byte, preview, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch_data,
            )

        # Create index on uri column for efficient filtering
        connection.execute("CREATE INDEX IF NOT EXISTS idx_uri ON chunks(uri)")

    return catalog


@pytest.mark.benchmark
class TestScopeFilteringPerformance:
    """Benchmark scope filtering performance overhead."""

    def test_baseline_query_by_ids(
        self, benchmark_catalog: DuckDBCatalog, benchmark
    ) -> None:
        """Benchmark baseline query_by_ids (no filtering).

        This establishes the baseline performance for retrieving chunks by ID
        without any filtering. All other benchmarks compare against this.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 100K chunks loaded.
        benchmark : pytest_benchmark.fixture.BenchmarkFixture
            pytest-benchmark fixture for timing.
        """
        # Select random chunk IDs for querying
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        def _query() -> list[dict]:
            return benchmark_catalog.query_by_ids(chunk_ids)

        result = benchmark(_query)
        assert len(result) == QUERY_CHUNK_COUNT
        assert all("id" in chunk for chunk in result)

    def test_language_filter_performance(
        self, benchmark_catalog: DuckDBCatalog, benchmark
    ) -> None:
        """Benchmark query_by_filters with language filter.

        Measures the overhead of filtering chunks by programming language
        (Python files only). Expected overhead: <5ms compared to baseline.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 100K chunks loaded.
        benchmark : pytest_benchmark.fixture.BenchmarkFixture
            pytest-benchmark fixture for timing.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        def _query() -> list[dict]:
            return benchmark_catalog.query_by_filters(chunk_ids, languages=["python"])

        result = benchmark(_query)
        # Verify filtering worked (should return only Python files)
        assert len(result) < QUERY_CHUNK_COUNT  # Some chunks filtered out
        assert all(chunk["uri"].endswith((".py", ".pyi")) for chunk in result)

    def test_path_glob_filter_performance(
        self, benchmark_catalog: DuckDBCatalog, benchmark
    ) -> None:
        """Benchmark query_by_filters with path glob pattern.

        Measures the overhead of filtering chunks by path pattern (src/**).
        Expected overhead: <5ms compared to baseline.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 100K chunks loaded.
        benchmark : pytest_benchmark.fixture.BenchmarkFixture
            pytest-benchmark fixture for timing.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        def _query() -> list[dict]:
            return benchmark_catalog.query_by_filters(
                chunk_ids, include_globs=["src/**"]
            )

        result = benchmark(_query)
        # Verify filtering worked (should return only src/ paths)
        assert len(result) < QUERY_CHUNK_COUNT  # Some chunks filtered out
        assert all(chunk["uri"].startswith("src/") for chunk in result)

    def test_combined_filters_performance(
        self, benchmark_catalog: DuckDBCatalog, benchmark
    ) -> None:
        """Benchmark query_by_filters with combined language and path filters.

        Measures the overhead of filtering chunks by both language and path
        patterns simultaneously. Expected overhead: <5ms compared to baseline.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 100K chunks loaded.
        benchmark : pytest_benchmark.fixture.BenchmarkFixture
            pytest-benchmark fixture for timing.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        def _query() -> list[dict]:
            return benchmark_catalog.query_by_filters(
                chunk_ids,
                include_globs=["src/**"],
                languages=["python"],
            )

        result = benchmark(_query)
        # Verify filtering worked (should return only Python files in src/)
        assert len(result) < QUERY_CHUNK_COUNT  # Some chunks filtered out
        assert all(
            chunk["uri"].startswith("src/") and chunk["uri"].endswith((".py", ".pyi"))
            for chunk in result
        )

    def test_complex_glob_filter_performance(
        self, benchmark_catalog: DuckDBCatalog, benchmark
    ) -> None:
        """Benchmark query_by_filters with complex glob pattern.

        Measures the overhead of filtering chunks using complex glob patterns
        that require Python post-filtering (e.g., src/**/test_*.py).
        Expected overhead: <10ms (higher than simple globs due to Python filtering).

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 100K chunks loaded.
        benchmark : pytest_benchmark.fixture.BenchmarkFixture
            pytest-benchmark fixture for timing.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        def _query() -> list[dict]:
            return benchmark_catalog.query_by_filters(
                chunk_ids, include_globs=["src/**/test_*.py"]
            )

        result = benchmark(_query)
        # Verify filtering worked (should return only test files in src/)
        assert len(result) < QUERY_CHUNK_COUNT  # Some chunks filtered out
        assert all(
            chunk["uri"].startswith("src/")
            and "test_" in chunk["uri"]
            and chunk["uri"].endswith(".py")
            for chunk in result
        )


@pytest.mark.benchmark
class TestScopeFilteringOverhead:
    """Verify scope filtering overhead meets performance requirements.

    These tests compare filtered queries against baseline to ensure overhead
    stays within acceptable limits (<5ms for typical queries).
    """

    def test_language_filter_overhead_acceptable(
        self, benchmark_catalog: DuckDBCatalog
    ) -> None:
        """Verify language filter overhead is <5ms.

        Compares language-filtered query performance against baseline and
        asserts that overhead is within acceptable threshold.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 10K chunks loaded.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        # Baseline: no filtering (run multiple times for average)
        baseline_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_ids(chunk_ids)
            baseline_times.append(perf_counter() - start)

        # Filtered: language filter (run multiple times for average)
        filtered_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_filters(chunk_ids, languages=["python"])
            filtered_times.append(perf_counter() - start)

        # Calculate overhead (in milliseconds)
        baseline_time_ms = (sum(baseline_times) / len(baseline_times)) * 1000
        filtered_time_ms = (sum(filtered_times) / len(filtered_times)) * 1000
        overhead_ms = filtered_time_ms - baseline_time_ms

        # Assert overhead is acceptable
        assert (
            overhead_ms < MAX_FILTER_OVERHEAD_MS
        ), f"Language filter overhead {overhead_ms:.2f}ms exceeds threshold {MAX_FILTER_OVERHEAD_MS}ms"

    def test_path_glob_filter_overhead_acceptable(
        self, benchmark_catalog: DuckDBCatalog
    ) -> None:
        """Verify path glob filter overhead is <5ms.

        Compares path-glob-filtered query performance against baseline and
        asserts that overhead is within acceptable threshold.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 10K chunks loaded.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        # Baseline: no filtering (run multiple times for average)
        baseline_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_ids(chunk_ids)
            baseline_times.append(perf_counter() - start)

        # Filtered: path glob filter (run multiple times for average)
        filtered_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_filters(chunk_ids, include_globs=["src/**"])
            filtered_times.append(perf_counter() - start)

        # Calculate overhead (in milliseconds)
        baseline_time_ms = (sum(baseline_times) / len(baseline_times)) * 1000
        filtered_time_ms = (sum(filtered_times) / len(filtered_times)) * 1000
        overhead_ms = filtered_time_ms - baseline_time_ms

        # Assert overhead is acceptable
        assert (
            overhead_ms < MAX_FILTER_OVERHEAD_MS
        ), f"Path glob filter overhead {overhead_ms:.2f}ms exceeds threshold {MAX_FILTER_OVERHEAD_MS}ms"

    def test_combined_filter_overhead_acceptable(
        self, benchmark_catalog: DuckDBCatalog
    ) -> None:
        """Verify combined filter overhead is <5ms.

        Compares combined (language + path) filter query performance against
        baseline and asserts that overhead is within acceptable threshold.

        Parameters
        ----------
        benchmark_catalog : DuckDBCatalog
            Catalog with 10K chunks loaded.
        """
        chunk_ids = list(range(1, QUERY_CHUNK_COUNT + 1))

        # Baseline: no filtering (run multiple times for average)
        baseline_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_ids(chunk_ids)
            baseline_times.append(perf_counter() - start)

        # Filtered: combined filters (run multiple times for average)
        filtered_times: list[float] = []
        for _ in range(100):
            start = perf_counter()
            benchmark_catalog.query_by_filters(
                chunk_ids,
                include_globs=["src/**"],
                languages=["python"],
            )
            filtered_times.append(perf_counter() - start)

        # Calculate overhead (in milliseconds)
        baseline_time_ms = (sum(baseline_times) / len(baseline_times)) * 1000
        filtered_time_ms = (sum(filtered_times) / len(filtered_times)) * 1000
        overhead_ms = filtered_time_ms - baseline_time_ms

        # Assert overhead is acceptable
        assert (
            overhead_ms < MAX_FILTER_OVERHEAD_MS
        ), f"Combined filter overhead {overhead_ms:.2f}ms exceeds threshold {MAX_FILTER_OVERHEAD_MS}ms"


def _run_hot_query(manager: DuckDBManager) -> None:
    """Execute a representative aggregation to exercise DuckDB planning."""
    with manager.connection() as conn:
        conn.execute(
            """
            SELECT avg(end_line - start_line)
            FROM chunks
            WHERE uri LIKE 'src/%'
            """
        ).fetchone()


def _average_duration(manager: DuckDBManager, iterations: int = 20) -> float:
    """Return the average execution time across repeated catalog queries.

    Parameters
    ----------
    manager : DuckDBManager
        DuckDB connection manager to use for queries.
    iterations : int, optional
        Number of query iterations to average. Defaults to 20.

    Returns
    -------
    float
        Average duration per query in seconds.
    """
    for _ in range(5):
        _run_hot_query(manager)
    start = perf_counter()
    for _ in range(iterations):
        _run_hot_query(manager)
    return (perf_counter() - start) / iterations


@pytest.mark.benchmark
def test_object_cache_benchmark(benchmark_catalog: DuckDBCatalog) -> None:
    """Benchmark object cache impact by comparing cached vs uncached query times."""
    benchmark_catalog.open()
    db_path = benchmark_catalog.db_path

    disabled = DuckDBManager(db_path, DuckDBConfig(enable_object_cache=False))
    enabled = DuckDBManager(db_path, DuckDBConfig(enable_object_cache=True))

    baseline = _average_duration(disabled)
    cached = _average_duration(enabled)

    assert (
        cached <= baseline * 1.5
    ), f"Object cache degraded query performance (cached={cached:.6f}s, baseline={baseline:.6f}s)"


def _write_materialization_dataset(vectors_dir: Path, row_count: int = 2_000) -> str:
    """Create a Parquet dataset used for materialization benchmarks.

    Parameters
    ----------
    vectors_dir : Path
        Directory where the Parquet file will be written.
    row_count : int, optional
        Number of rows to generate in the dataset. Defaults to 2_000.

    Returns
    -------
    str
        Absolute path to the generated Parquet file.
    """
    parquet_path = vectors_dir / "chunks.parquet"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE tmp (
                id BIGINT,
                uri VARCHAR,
                start_line INTEGER,
                end_line INTEGER,
                start_byte BIGINT,
                end_byte BIGINT,
                preview VARCHAR,
                embedding FLOAT[]
            )
            """
        )
        rows = []
        for i in range(1, row_count + 1):
            uri = f"src/module_{i}.py" if i % 2 == 0 else f"tests/test_{i}.py"
            rows.append(
                (i, uri, 1, 100, 0, 400, f"code snippet {i}", [0.1, 0.2]),
            )
        connection.executemany(
            """
            INSERT INTO tmp
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(parquet_path)])
    return str(parquet_path)


@pytest.mark.benchmark
def test_materialized_vs_view_performance(tmp_path) -> None:
    """Validate materialized catalogs are not slower than view-based catalogs."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    _write_materialization_dataset(vectors_dir)

    view_catalog = DuckDBCatalog(
        tmp_path / "view.duckdb", vectors_dir, materialize=False
    )
    materialized_catalog = DuckDBCatalog(
        tmp_path / "materialized.duckdb",
        vectors_dir,
        materialize=True,
    )

    view_catalog.open()
    materialized_catalog.open()

    chunk_ids = list(range(1, 1001))

    def _measure(catalog: DuckDBCatalog) -> float:
        iterations = 15
        for _ in range(3):
            catalog.query_by_ids(chunk_ids)
        start = perf_counter()
        for _ in range(iterations):
            catalog.query_by_ids(chunk_ids)
        return (perf_counter() - start) / iterations

    view_time = _measure(view_catalog)
    materialized_time = _measure(materialized_catalog)

    assert materialized_time <= view_time * 1.2, (
        "Materialized catalog slower than view "
        f"(materialized={materialized_time:.6f}s, view={view_time:.6f}s)"
    )
