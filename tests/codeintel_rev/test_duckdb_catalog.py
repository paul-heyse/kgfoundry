"""Unit tests for DuckDB catalog query_by_filters method.

Tests verify path and language filtering functionality, including:
- Simple glob pattern conversion to SQL LIKE
- Complex glob pattern fallback to Python fnmatch
- Language filtering via extension mapping
- Combined filters (include, exclude, languages)
- Edge cases (empty filters, no matches, etc.)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBQueryOptions

ALL_CHUNK_IDS = list(range(1, 12))


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
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = ?
            """,
            [table_name],
        ).fetchone()
        return bool(row and row[0])
    finally:
        connection.close()


def _index_exists(db_path: Path, index_name: str) -> bool:
    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM duckdb_indexes() WHERE index_name = ?",
            [index_name],
        ).fetchone()
        return bool(row and row[0])
    finally:
        connection.close()


@pytest.fixture
def test_catalog(tmp_path: Path) -> DuckDBCatalog:
    """Create an in-memory DuckDB catalog with test chunks.

    Creates a DuckDB catalog and inserts test chunks with various URIs
    and languages for testing filtering functionality.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for DuckDB database file.

    Returns
    -------
    DuckDBCatalog
        Catalog instance with test data loaded.
    """
    db_path = tmp_path / "test.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog = DuckDBCatalog(db_path, vectors_dir)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE chunks AS
            SELECT * FROM VALUES
                (1::BIGINT, 'src/main.py'::VARCHAR, 1::INTEGER, 10::INTEGER, 0::BIGINT, 100::BIGINT, 'def main():'::VARCHAR, [0.1, 0.2]::FLOAT[]),
                (2::BIGINT, 'src/utils.py'::VARCHAR, 5::INTEGER, 15::INTEGER, 50::BIGINT, 150::BIGINT, 'def helper():'::VARCHAR, [0.3, 0.4]::FLOAT[]),
                (3::BIGINT, 'tests/test_main.py'::VARCHAR, 1::INTEGER, 5::INTEGER, 0::BIGINT, 50::BIGINT, 'def test_main():'::VARCHAR, [0.5, 0.6]::FLOAT[]),
                (4::BIGINT, 'tests/test_utils.py'::VARCHAR, 1::INTEGER, 5::INTEGER, 0::BIGINT, 50::BIGINT, 'def test_helper():'::VARCHAR, [0.7, 0.8]::FLOAT[]),
                (5::BIGINT, 'src/app.ts'::VARCHAR, 1::INTEGER, 20::INTEGER, 0::BIGINT, 200::BIGINT, 'function app() {'::VARCHAR, [0.9, 1.0]::FLOAT[]),
                (6::BIGINT, 'src/components/Button.tsx'::VARCHAR, 1::INTEGER, 30::INTEGER, 0::BIGINT, 300::BIGINT, 'export const Button'::VARCHAR, [1.1, 1.2]::FLOAT[]),
                (7::BIGINT, 'docs/README.md'::VARCHAR, 1::INTEGER, 50::INTEGER, 0::BIGINT, 500::BIGINT, '# Documentation'::VARCHAR, [1.3, 1.4]::FLOAT[]),
                (8::BIGINT, 'src/nested/deep/file.py'::VARCHAR, 1::INTEGER, 5::INTEGER, 0::BIGINT, 50::BIGINT, 'deep code'::VARCHAR, [1.5, 1.6]::FLOAT[]),
                (9::BIGINT, 'lib/legacy.py'::VARCHAR, 1::INTEGER, 10::INTEGER, 0::BIGINT, 100::BIGINT, 'old code'::VARCHAR, [1.7, 1.8]::FLOAT[]),
                (10::BIGINT, 'src/config.json'::VARCHAR, 1::INTEGER, 5::INTEGER, 0::BIGINT, 50::BIGINT, '{"key": "value"}'::VARCHAR, [1.9, 2.0]::FLOAT[]),
                (11::BIGINT, 'main.py'::VARCHAR, 1::INTEGER, 20::INTEGER, 0::BIGINT, 200::BIGINT, 'def entry():'::VARCHAR, [2.1, 2.2]::FLOAT[])
            AS t(id, uri, start_line, end_line, start_byte, end_byte, preview, embedding)
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_uri ON chunks(uri)")

    return catalog


class TestQueryByFiltersIncludeGlobs:
    """Test include glob pattern filtering."""

    def test_include_glob_python_files(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by Python file pattern."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["**/*.py"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
            "tests/test_utils.py",
            "src/nested/deep/file.py",
            "lib/legacy.py",
            "main.py",
        }
        assert len(results) == 7

    def test_include_glob_src_prefix(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by src/ prefix pattern."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "src/app.ts",
            "src/components/Button.tsx",
            "src/nested/deep/file.py",
            "src/config.json",
        }
        assert len(results) == 6

    def test_include_glob_simple_suffix(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by simple suffix pattern."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["*.ts"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {"src/app.ts"}
        assert len(results) == 1

    def test_include_glob_multiple_patterns(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by multiple include patterns (OR logic)."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["**/*.py", "**/*.tsx"],
        )

        uris = {r["uri"] for r in results}
        assert "src/main.py" in uris
        assert "src/components/Button.tsx" in uris
        assert "src/app.ts" not in uris  # .ts not .tsx
        assert "main.py" in uris
        assert len(results) == 8  # 7 Python + 1 TSX

    def test_include_glob_empty_list(self, test_catalog: DuckDBCatalog) -> None:
        """Test that empty include globs means include all."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            include_globs=[],
        )

        assert len(results) == 3
        uris = {r["uri"] for r in results}
        assert uris == {"src/main.py", "src/utils.py", "tests/test_main.py"}


class TestQueryByFiltersExcludeGlobs:
    """Test exclude glob pattern filtering."""

    def test_exclude_glob_test_files(self, test_catalog: DuckDBCatalog) -> None:
        """Test excluding test files."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            exclude_globs=["**/test_*.py"],
        )

        uris = {r["uri"] for r in results}
        assert "tests/test_main.py" not in uris
        assert "tests/test_utils.py" not in uris
        assert "src/main.py" in uris
        assert "main.py" in uris
        assert len(results) == 9

    def test_exclude_glob_multiple_patterns(self, test_catalog: DuckDBCatalog) -> None:
        """Test excluding multiple patterns."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            exclude_globs=["**/test_*.py", "**/*.md"],
        )

        uris = {r["uri"] for r in results}
        assert "tests/test_main.py" not in uris
        assert "tests/test_utils.py" not in uris
        assert "docs/README.md" not in uris
        assert len(results) == 8

    def test_exclude_glob_empty_list(self, test_catalog: DuckDBCatalog) -> None:
        """Test that empty exclude globs means exclude none."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            exclude_globs=[],
        )

        assert len(results) == 3


class TestQueryByFiltersLanguageFilter:
    """Test language-based filtering."""

    def test_language_filter_python(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by Python language."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
            "tests/test_utils.py",
            "src/nested/deep/file.py",
            "lib/legacy.py",
            "main.py",
        }
        assert len(results) == 7

    def test_language_filter_typescript(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by TypeScript language."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["typescript"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {"src/app.ts", "src/components/Button.tsx"}
        assert len(results) == 2

    def test_language_filter_multiple(self, test_catalog: DuckDBCatalog) -> None:
        """Test filtering by multiple languages."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["python", "typescript"],
        )

        uris = {r["uri"] for r in results}
        assert "src/main.py" in uris
        assert "src/app.ts" in uris
        assert "src/components/Button.tsx" in uris
        assert "docs/README.md" not in uris
        assert "main.py" in uris
        assert len(results) == 9  # 7 Python + 2 TypeScript

    def test_language_filter_unknown_language(
        self, test_catalog: DuckDBCatalog
    ) -> None:
        """Test filtering by unknown language returns empty."""
        # Note: query_by_filters imports LANGUAGE_EXTENSIONS from scope_utils
        # If language has no extensions, the SQL query filters by empty extension set
        # which matches nothing, so results should be empty
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            languages=["cobol"],
        )

        # Unknown language has no extensions, so no chunks match
        assert len(results) == 0

    def test_language_filter_empty_list(self, test_catalog: DuckDBCatalog) -> None:
        """Test that empty language list means no filtering."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            languages=[],
        )

        assert len(results) == 3


class TestQueryByFiltersCombined:
    """Test combined filters (include, exclude, languages)."""

    def test_include_and_exclude(self, test_catalog: DuckDBCatalog) -> None:
        """Test combining include and exclude globs."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["**/*.py"],
            exclude_globs=["**/test_*.py"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "src/nested/deep/file.py",
            "lib/legacy.py",
            "main.py",
        }
        assert "tests/test_main.py" not in uris
        assert len(results) == 5

    def test_include_and_language(self, test_catalog: DuckDBCatalog) -> None:
        """Test combining include globs and language filter."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "src/nested/deep/file.py",
        }
        assert "src/app.ts" not in uris  # Not Python
        assert "src/config.json" not in uris  # Not Python
        assert len(results) == 3

    def test_exclude_and_language(self, test_catalog: DuckDBCatalog) -> None:
        """Test combining exclude globs and language filter."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            exclude_globs=["**/test_*.py"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "src/nested/deep/file.py",
            "lib/legacy.py",
            "main.py",
        }
        assert "tests/test_main.py" not in uris
        assert len(results) == 5

    def test_all_filters_combined(self, test_catalog: DuckDBCatalog) -> None:
        """Test combining all three filter types."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**"],
            exclude_globs=["**/test_*.py"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {
            "src/main.py",
            "src/utils.py",
            "src/nested/deep/file.py",
        }
        assert len(results) == 3


class TestQueryByFiltersComplexGlobs:
    """Test complex glob patterns that fall back to Python filtering."""

    def test_complex_glob_recursive_middle(self, test_catalog: DuckDBCatalog) -> None:
        """Test complex glob with ** in middle (requires Python filtering)."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**/file.py"],
        )

        uris = {r["uri"] for r in results}
        assert uris == {"src/nested/deep/file.py"}
        assert len(results) == 1

    def test_complex_glob_bracket_expression(self, test_catalog: DuckDBCatalog) -> None:
        """Test glob with bracket expression (requires Python filtering)."""
        # Note: fnmatch doesn't support bracket expressions the same way as bash,
        # but we test that complex patterns trigger Python filtering
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/[mn]*.py"],
        )

        # This should match src/main.py (m*) but not src/utils.py
        uris = {r["uri"] for r in results}
        assert "src/main.py" in uris
        assert len(results) >= 1


class TestQueryByFiltersEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_no_filters(self, test_catalog: DuckDBCatalog) -> None:
        """Test that no filters behaves like query_by_ids."""
        ids = [1, 2, 3]
        results_filtered = test_catalog.query_by_filters(ids)
        results_ids = test_catalog.query_by_ids(ids)

        assert len(results_filtered) == len(results_ids)
        assert {r["id"] for r in results_filtered} == {r["id"] for r in results_ids}

    def test_empty_ids(self, test_catalog: DuckDBCatalog) -> None:
        """Test that empty ID list returns empty results."""
        results = test_catalog.query_by_filters(
            [],
            include_globs=["**/*.py"],
        )

        assert len(results) == 0

    def test_no_matches(self, test_catalog: DuckDBCatalog) -> None:
        """Test that filters matching no chunks return empty."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            include_globs=["**/*.java"],
        )

        assert len(results) == 0

    def test_none_filters(self, test_catalog: DuckDBCatalog) -> None:
        """Test that None filters behave like no filters."""
        ids = [1, 2, 3]
        results_none = test_catalog.query_by_filters(
            ids,
            include_globs=None,
            exclude_globs=None,
            languages=None,
        )
        results_no_filters = test_catalog.query_by_filters(ids)

        assert len(results_none) == len(results_no_filters)

    def test_preserves_id_order(self, test_catalog: DuckDBCatalog) -> None:
        """Test that results preserve input ID order."""
        ids = [10, 5, 1, 8, 3]
        results = test_catalog.query_by_filters(
            ids,
            include_globs=["**/*.py"],
        )

        result_ids = [r["id"] for r in results]
        # Should preserve order of input IDs (filtered)
        # Input order: [10, 5, 1, 8, 3]
        # ID 10: src/config.json - filtered out (not .py)
        # ID 5: src/app.ts - filtered out (not .py)
        # ID 1: src/main.py - matches
        # ID 8: src/nested/deep/file.py - matches
        # ID 3: tests/test_main.py - matches
        # Expected order: [1, 8, 3] (preserving input order after filtering)
        expected_ids = [1, 8, 3]  # 10 and 5 filtered out (not .py)
        assert result_ids == expected_ids


class TestConcurrentAccess:
    """Concurrency tests ensuring DuckDBCatalog handles parallel queries safely."""

    def test_query_by_filters_thread_safe(self, test_catalog: DuckDBCatalog) -> None:
        """Execute 100 concurrent filter queries without race conditions."""
        test_catalog.open()

        expected_uris = {
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
            "tests/test_utils.py",
            "src/nested/deep/file.py",
            "lib/legacy.py",
            "main.py",
        }

        def _worker() -> set[str]:
            results = test_catalog.query_by_filters(
                ALL_CHUNK_IDS,
                include_globs=["**/*.py"],
            )
            return {row["uri"] for row in results}

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(_worker) for _ in range(100)]
            results = [future.result() for future in futures]

        for uris in results:
            assert uris == expected_uris

    def test_query_without_explicit_open(self, tmp_path: Path) -> None:
        """query_by_filters should lazily initialize without calling open()."""
        db_path = tmp_path / "test.duckdb"
        vectors_dir = tmp_path / "vectors"
        vectors_dir.mkdir()

        catalog = DuckDBCatalog(db_path, vectors_dir)
        result = catalog.query_by_filters([1, 2, 3], include_globs=["**/*.py"])
        assert result == []


def test_query_by_filters_uses_query_builder(
    test_catalog: DuckDBCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """query_by_filters delegates SQL generation to DuckDBQueryBuilder."""
    calls: list[dict[str, object]] = []

    def _fake_build_filter_query(
        *,
        chunk_ids: list[int],
        options: DuckDBQueryOptions | None = None,
    ) -> tuple[str, dict[str, list[int]]]:
        calls.append(
            {
                "chunk_ids": list(chunk_ids),
                "options": options,
            }
        )
        sql = (
            "SELECT c.*\n"
            "FROM chunks AS c\n"
            "JOIN UNNEST($ids) WITH ORDINALITY AS ids(id, position)\n"
            "  ON c.id = ids.id\n"
            "ORDER BY ids.position"
        )
        return sql, {"ids": list(chunk_ids)}

    monkeypatch.setattr(
        test_catalog,
        "_query_builder",
        SimpleNamespace(build_filter_query=_fake_build_filter_query),
    )

    results = test_catalog.query_by_filters([1, 2])

    assert len(results) == 2
    assert calls, "DuckDBQueryBuilder.build_filter_query should be invoked"
    recorded = calls[0]
    options = recorded["options"]
    assert isinstance(options, DuckDBQueryOptions)
    assert options.preserve_order is True
    assert options.select_columns == ("c.*",)
    assert options.include_globs is None
    assert options.exclude_globs is None


class TestQueryByFiltersParametrized:
    """Parametrized tests for combinatorial coverage."""

    @pytest.mark.parametrize(
        ("include_glob", "expected_count"),
        [
            ("**/*.py", 7),
            ("src/**", 6),
            ("tests/**", 2),
            ("**/*.ts", 1),
            ("**/*.tsx", 1),
            ("**/*.md", 1),
            ("**/*.json", 1),
        ],
    )
    def test_include_glob_patterns(
        self,
        test_catalog: DuckDBCatalog,
        include_glob: str,
        expected_count: int,
    ) -> None:
        """Test various include glob patterns."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=[include_glob],
        )

        assert len(results) == expected_count


def test_query_by_uri_supports_unlimited_results(tmp_path: Path) -> None:
    """Unlimited ``limit`` arguments return all matches."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunks_parquet(parquet_path)

    db_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(db_path, vectors_dir)
    parquet_expr = str(parquet_path).replace("'", "''")
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            f"CREATE OR REPLACE VIEW chunks AS SELECT * FROM read_parquet('{parquet_expr}')"  # noqa: S608
        )

    limited = catalog.query_by_uri("example.py", limit=1)
    unlimited_zero = catalog.query_by_uri("example.py", limit=0)
    unlimited_negative = catalog.query_by_uri("example.py", limit=-1)

    catalog.close()

    assert [row["id"] for row in limited] == [1]
    assert [row["id"] for row in unlimited_zero] == [1, 2]
    assert unlimited_zero == unlimited_negative


def test_get_embeddings_by_ids_skips_null_embeddings(tmp_path: Path) -> None:
    """Rows with NULL embeddings are ignored when fetching vectors."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT 1::BIGINT AS id, [0.1, 0.2]::FLOAT[] AS embedding
                UNION ALL
                SELECT 2::BIGINT AS id, NULL::FLOAT[] AS embedding
            )
            """
        )

    results = catalog.get_embeddings_by_ids([1, 2])
    assert results.shape == (1, 2)
    assert np.allclose(results[0], [0.1, 0.2])


def test_query_by_filters_handles_literal_percent(tmp_path: Path) -> None:
    """Percent characters are treated as literals inside glob filters."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT
                    1::BIGINT AS id,
                    'src/config%file.py'::VARCHAR AS uri,
                    0::INTEGER AS start_line,
                    1::INTEGER AS end_line,
                    0::BIGINT AS start_byte,
                    10::BIGINT AS end_byte,
                    'percent file'::VARCHAR AS preview,
                    [0.1, 0.2]::FLOAT[] AS embedding
            )
            """
        )

    results = catalog.query_by_filters([1], include_globs=["src/config%file.py"])
    assert len(results) == 1
    assert results[0]["uri"] == "src/config%file.py"


def test_query_by_filters_handles_literal_underscore(tmp_path: Path) -> None:
    """Underscore characters are treated as literals inside glob filters."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
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
    """Materialization builds a table and supporting index."""
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
        row = connection.execute("SELECT COUNT(*) FROM chunks_materialized").fetchone()
        row_count = row[0] if row else 0
    finally:
        connection.close()

    assert row_count == 3


def test_materialize_creates_empty_table_when_parquet_missing(tmp_path: Path) -> None:
    """Materialization creates empty table when parquet inputs are absent."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assert catalog.count_chunks() == 0

    assert _table_exists(catalog_path, "chunks_materialized") is True
    assert _index_exists(catalog_path, "idx_chunks_materialized_uri") is True

    @pytest.mark.parametrize(
        ("language", "expected_count"),
        [
            ("python", 7),
            ("typescript", 2),
            ("javascript", 0),  # No .js files in test data
            ("rust", 0),  # No .rs files in test data
        ],
    )
    def test_language_filters(
        test_catalog: DuckDBCatalog,
        language: str,
        expected_count: int,
    ) -> None:
        """Test various language filters."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=[language],
        )

        assert len(results) == expected_count
