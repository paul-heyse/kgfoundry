"""Unit tests for DuckDB catalog query_by_filters method.

Tests verify path and language filtering functionality, including:
- Simple glob pattern conversion to SQL LIKE
- Complex glob pattern fallback to Python fnmatch
- Language filtering via extension mapping
- Combined filters (include, exclude, languages)
- Edge cases (empty filters, no matches, etc.)
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
import pytest
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions, relation_exists
from codeintel_rev.io.duckdb_manager import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions

from tests._helpers import assertions
from tests._helpers.duckdb_catalog import (
    default_chunk_rows,
    index_exists,
    safe_sql_path,
    seed_chunks_table,
    table_exists,
    write_chunks_parquet,
    write_idmap_parquet,
    write_single_row_parquet,
)

ALL_CHUNK_IDS = list(range(1, 12))


def test_ensure_struct_views_materializes(tmp_path: Path) -> None:
    """Structured assets register views and materialized tables."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    chunks_path = vectors_dir / "chunks.parquet"
    write_single_row_parquet(
        chunks_path,
        """
        SELECT
            1::BIGINT AS id,
            'repo://module.py'::VARCHAR AS uri,
            0::INTEGER AS start_line,
            4::INTEGER AS end_line,
            0::BIGINT AS start_byte,
            40::BIGINT AS end_byte,
            'preview'::VARCHAR AS preview,
            'content'::VARCHAR AS content,
            'python'::VARCHAR AS lang,
            ['symbol.mod']::VARCHAR[] AS symbols,
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )
    modules_path = tmp_path / "modules.parquet"
    write_single_row_parquet(
        modules_path,
        """
        SELECT
            'repo://module.py'::VARCHAR AS uri,
            'repo://module.py'::VARCHAR AS repo_path,
            'module.mod'::VARCHAR AS module_name
        """,
    )
    scip_path = tmp_path / "scip.parquet"
    write_single_row_parquet(
        scip_path,
        """
        SELECT
            'symbol.mod'::VARCHAR AS symbol,
            'definition'::VARCHAR AS role,
            'repo://module.py'::VARCHAR AS uri
        """,
    )
    ast_path = tmp_path / "ast.parquet"
    write_single_row_parquet(
        ast_path,
        """
        SELECT
            'repo://module.py'::VARCHAR AS uri,
            'FunctionDef'::VARCHAR AS node_type,
            0::BIGINT AS start_byte,
            10::BIGINT AS end_byte
        """,
    )
    cst_path = tmp_path / "cst.parquet"
    write_single_row_parquet(
        cst_path,
        """
        SELECT
            'repo://module.py'::VARCHAR AS uri,
            'function_definition'::VARCHAR AS kind,
            0::INTEGER AS start_line,
            4::INTEGER AS end_line
        """,
    )

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    catalog.ensure_struct_views(
        modules_parquet=modules_path,
        scip_occurrences_parquet=scip_path,
        ast_nodes_parquet=ast_path,
        cst_nodes_parquet=cst_path,
        materialize=True,
    )

    with duckdb.connect(str(catalog_path)) as connection:
        for view_name in ("modules", "scip_occurrences", "ast_nodes", "cst_nodes"):
            assertions.expect_true(
                relation_exists(connection, view_name), reason=f"{view_name} view should exist"
            )
        assertions.expect_true(
            relation_exists(connection, "v_chunk_symbols"),
            reason="v_chunk_symbols view should exist",
        )
        for table_name in (
            "modules_mat",
            "scip_occurrences_mat",
            "ast_nodes_mat",
            "cst_nodes_mat",
        ):
            assertions.expect_true(
                relation_exists(connection, table_name), reason=f"{table_name} table should exist"
            )
            row = connection.table(table_name).aggregate("count(*) AS row_count").fetchone()
            assertions.expect_true(row is not None, reason=f"{table_name} should have rows")
            if row is None:  # pragma: no cover - defensive for type checkers
                pytest.fail(f"{table_name} should have rows")
            assertions.expect_equal(row[0], 1)


@pytest.fixture
def test_catalog(tmp_path: Path) -> DuckDBCatalog:
    """Create a DuckDB catalog seeded with standard chunk rows."""
    db_path = tmp_path / "test.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog = DuckDBCatalog(db_path, vectors_dir)
    with duckdb.connect(str(db_path)) as connection:
        seed_chunks_table(connection, default_chunk_rows())
    return catalog


class TestQueryByFiltersIncludeGlobs:
    """Test include glob pattern filtering."""

    @pytest.mark.parametrize(
        ("include_globs", "expected_uris"),
        [
            (
                ["**/*.py"],
                {
                    "src/main.py",
                    "src/utils.py",
                    "tests/test_main.py",
                    "tests/test_utils.py",
                    "src/nested/deep/file.py",
                    "lib/legacy.py",
                    "main.py",
                },
            ),
            (
                ["src/**"],
                {
                    "src/main.py",
                    "src/utils.py",
                    "src/app.ts",
                    "src/components/Button.tsx",
                    "src/nested/deep/file.py",
                    "src/config.json",
                },
            ),
            (["*.ts"], {"src/app.ts"}),
            (
                ["**/*.py", "**/*.tsx"],
                {
                    "src/main.py",
                    "src/utils.py",
                    "tests/test_main.py",
                    "tests/test_utils.py",
                    "src/nested/deep/file.py",
                    "lib/legacy.py",
                    "main.py",
                    "src/components/Button.tsx",
                },
            ),
        ],
    )
    def test_include_globs(
        self, test_catalog: DuckDBCatalog, include_globs: list[str], expected_uris: set[str]
    ) -> None:
        """Include globs filter results as expected."""
        results = test_catalog.query_by_filters(ALL_CHUNK_IDS, include_globs=include_globs)
        uris = {r["uri"] for r in results}
        assertions.expect_equal(uris, expected_uris)
        assertions.expect_equal(len(results), len(expected_uris))

    def test_include_glob_empty_list(self, test_catalog: DuckDBCatalog) -> None:
        """Empty include globs returns provided ids."""
        results = test_catalog.query_by_filters([1, 2, 3], include_globs=[])
        assertions.expect_equal(len(results), 3)
        uris = {r["uri"] for r in results}
        assertions.expect_equal(uris, {"src/main.py", "src/utils.py", "tests/test_main.py"})


class TestQueryByFiltersExcludeGlobs:
    """Test exclude glob pattern filtering."""

    @pytest.mark.parametrize(
        ("exclude_globs", "excluded", "expected_count"),
        [
            (["**/test_*.py"], {"tests/test_main.py", "tests/test_utils.py"}, 9),
            (
                ["**/test_*.py", "**/*.md"],
                {"tests/test_main.py", "tests/test_utils.py", "docs/README.md"},
                8,
            ),
        ],
    )
    def test_exclude_globs(
        self,
        test_catalog: DuckDBCatalog,
        exclude_globs: list[str],
        excluded: set[str],
        expected_count: int,
    ) -> None:
        """Exclude globs filter out the targeted URIs."""
        results = test_catalog.query_by_filters(ALL_CHUNK_IDS, exclude_globs=exclude_globs)
        uris = {r["uri"] for r in results}
        for uri in excluded:
            assertions.expect_false(uri in uris)
        assertions.expect_equal(len(results), expected_count)

    @staticmethod
    def test_exclude_glob_empty_list(test_catalog: DuckDBCatalog) -> None:
        """Empty exclude globs returns provided ids."""
        results = test_catalog.query_by_filters([1, 2, 3], exclude_globs=[])
        assertions.expect_equal(len(results), 3)


class TestQueryByFiltersLanguageFilter:
    """Test language-based filtering."""

    @staticmethod
    def test_language_filter_python(test_catalog: DuckDBCatalog) -> None:
        """Test filtering by Python language."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(
            uris,
            {
                "src/main.py",
                "src/utils.py",
                "tests/test_main.py",
                "tests/test_utils.py",
                "src/nested/deep/file.py",
                "lib/legacy.py",
                "main.py",
            },
        )
        assertions.expect_equal(len(results), 7)

    @staticmethod
    def test_language_filter_typescript(test_catalog: DuckDBCatalog) -> None:
        """Test filtering by TypeScript language."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["typescript"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(uris, {"src/app.ts", "src/components/Button.tsx"})
        assertions.expect_equal(len(results), 2)

    @staticmethod
    def test_language_filter_multiple(test_catalog: DuckDBCatalog) -> None:
        """Test filtering by multiple languages."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            languages=["python", "typescript"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_in("src/main.py", uris)
        assertions.expect_in("src/app.ts", uris)
        assertions.expect_in("src/components/Button.tsx", uris)
        assertions.expect_false("docs/README.md" in uris, reason="markdown should not be included")
        assertions.expect_in("main.py", uris)
        assertions.expect_equal(len(results), 9)  # 7 Python + 2 TypeScript

    @staticmethod
    def test_language_filter_unknown_language(test_catalog: DuckDBCatalog) -> None:
        """Test filtering by unknown language returns empty."""
        # Note: query_by_filters imports LANGUAGE_EXTENSIONS from scope_utils
        # If language has no extensions, the SQL query filters by empty extension set
        # which matches nothing, so results should be empty
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            languages=["cobol"],
        )

        # Unknown language has no extensions, so no chunks match
        assertions.expect_equal(len(results), 0)

    @staticmethod
    def test_language_filter_empty_list(test_catalog: DuckDBCatalog) -> None:
        """Test that empty language list means no filtering."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            languages=[],
        )

        assertions.expect_equal(len(results), 3)


class TestQueryByFiltersCombined:
    """Test combined filters (include, exclude, languages)."""

    @staticmethod
    def test_include_and_exclude(test_catalog: DuckDBCatalog) -> None:
        """Test combining include and exclude globs."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["**/*.py"],
            exclude_globs=["**/test_*.py"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(
            uris,
            {
                "src/main.py",
                "src/utils.py",
                "src/nested/deep/file.py",
                "lib/legacy.py",
                "main.py",
            },
        )
        assertions.expect_false(
            "tests/test_main.py" in uris, reason="test files should be excluded"
        )
        assertions.expect_equal(len(results), 5)

    @staticmethod
    def test_include_and_language(test_catalog: DuckDBCatalog) -> None:
        """Test combining include globs and language filter."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(
            uris,
            {
                "src/main.py",
                "src/utils.py",
                "src/nested/deep/file.py",
            },
        )
        assertions.expect_false("src/app.ts" in uris, reason="Not Python")
        assertions.expect_false("src/config.json" in uris, reason="Not Python")
        assertions.expect_equal(len(results), 3)

    @staticmethod
    def test_exclude_and_language(test_catalog: DuckDBCatalog) -> None:
        """Test combining exclude globs and language filter."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            exclude_globs=["**/test_*.py"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(
            uris,
            {
                "src/main.py",
                "src/utils.py",
                "src/nested/deep/file.py",
                "lib/legacy.py",
                "main.py",
            },
        )
        assertions.expect_false(
            "tests/test_main.py" in uris, reason="test files should be excluded"
        )
        assertions.expect_equal(len(results), 5)

    @staticmethod
    def test_all_filters_combined(test_catalog: DuckDBCatalog) -> None:
        """Test combining all three filter types."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**"],
            exclude_globs=["**/test_*.py"],
            languages=["python"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(
            uris,
            {
                "src/main.py",
                "src/utils.py",
                "src/nested/deep/file.py",
            },
        )
        assertions.expect_equal(len(results), 3)


class TestQueryByFiltersComplexGlobs:
    """Test complex glob patterns that fall back to Python filtering."""

    @staticmethod
    def test_complex_glob_recursive_middle(test_catalog: DuckDBCatalog) -> None:
        """Test complex glob with ** in middle (requires Python filtering)."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/**/file.py"],
        )

        uris = {r["uri"] for r in results}
        assertions.expect_equal(uris, {"src/nested/deep/file.py"})
        assertions.expect_equal(len(results), 1)

    @staticmethod
    def test_complex_glob_bracket_expression(test_catalog: DuckDBCatalog) -> None:
        """Test glob with bracket expression (requires Python filtering)."""
        # Note: fnmatch doesn't support bracket expressions the same way as bash,
        # but we test that complex patterns trigger Python filtering
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=["src/[mn]*.py"],
        )

        # This should match src/main.py (m*) but not src/utils.py
        uris = {r["uri"] for r in results}
        assertions.expect_in("src/main.py", uris)
        assertions.expect_true(len(results) >= 1, reason="should match at least one file")


class TestQueryByFiltersEdgeCases:
    """Test edge cases and boundary conditions."""

    @staticmethod
    def test_no_filters(test_catalog: DuckDBCatalog) -> None:
        """Test that no filters behaves like query_by_ids."""
        ids = [1, 2, 3]
        results_filtered = test_catalog.query_by_filters(ids)
        results_ids = test_catalog.query_by_ids(ids)

        assertions.expect_equal(len(results_filtered), len(results_ids))
        assertions.expect_equal({r["id"] for r in results_filtered}, {r["id"] for r in results_ids})

    @staticmethod
    def test_empty_ids(test_catalog: DuckDBCatalog) -> None:
        """Test that empty ID list returns empty results."""
        results = test_catalog.query_by_filters(
            [],
            include_globs=["**/*.py"],
        )

        assertions.expect_equal(len(results), 0)

    @staticmethod
    def test_no_matches(test_catalog: DuckDBCatalog) -> None:
        """Test that filters matching no chunks return empty."""
        results = test_catalog.query_by_filters(
            [1, 2, 3],
            include_globs=["**/*.java"],
        )

        assertions.expect_equal(len(results), 0)

    @staticmethod
    def test_none_filters(test_catalog: DuckDBCatalog) -> None:
        """Test that None filters behave like no filters."""
        ids = [1, 2, 3]
        results_none = test_catalog.query_by_filters(
            ids,
            include_globs=None,
            exclude_globs=None,
            languages=None,
        )
        results_no_filters = test_catalog.query_by_filters(ids)

        assertions.expect_equal(len(results_none), len(results_no_filters))

    @staticmethod
    def test_preserves_id_order(test_catalog: DuckDBCatalog) -> None:
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
        assertions.expect_sequence_equal(result_ids, expected_ids)


class TestConcurrentAccess:
    """Concurrency tests ensuring DuckDBCatalog handles parallel queries safely."""

    @staticmethod
    def test_query_by_filters_thread_safe(test_catalog: DuckDBCatalog) -> None:
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
            """Execute filter query and return URI set.

            Returns
            -------
            set[str]
                Set of URIs from query results.
            """
            results = test_catalog.query_by_filters(
                ALL_CHUNK_IDS,
                include_globs=["**/*.py"],
            )
            return {row["uri"] for row in results}

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(_worker) for _ in range(100)]
            results = [future.result() for future in futures]

        for uris in results:
            assertions.expect_equal(uris, expected_uris)

    @staticmethod
    def test_query_without_explicit_open(tmp_path: Path) -> None:
        """query_by_filters should lazily initialize without calling open()."""
        db_path = tmp_path / "test.duckdb"
        vectors_dir = tmp_path / "vectors"
        vectors_dir.mkdir()

        catalog = DuckDBCatalog(db_path, vectors_dir)
        result = catalog.query_by_filters([1, 2, 3], include_globs=["**/*.py"])
        assertions.expect_equal(result, [])


def test_query_by_filters_uses_query_builder(test_catalog: DuckDBCatalog) -> None:
    """query_by_filters delegates SQL generation to DuckDBQueryBuilder."""

    class _RecordingBuilder(DuckDBQueryBuilder):
        """Query builder that records all build_filter_query calls."""

        def __init__(self) -> None:
            """Initialize recording builder with empty calls list."""
            self.calls: list[dict[str, object]] = []

        def build_filter_query(
            self,
            *,
            chunk_ids: Sequence[int],
            options: DuckDBQueryOptions | None = None,
        ) -> tuple[str, dict[str, list[int] | list[str] | str]]:
            """Record call and return test SQL query.

            Parameters
            ----------
            chunk_ids : Sequence[int]
                Chunk IDs to filter by.
            options : DuckDBQueryOptions | None, optional
                Query options (unused in test implementation).

            Returns
            -------
            tuple[str, dict[str, list[int] | list[str] | str]]
                SQL query string and parameters dictionary.
            """
            self.calls.append(
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

    builder = _RecordingBuilder()
    catalog = DuckDBCatalog(
        test_catalog.db_path,
        test_catalog.vectors_dir,
        options=DuckDBCatalogOptions(
            manager=DuckDBManager(test_catalog.db_path),
            query_builder_factory=lambda: builder,
        ),
    )

    results = catalog.query_by_filters([1, 2])

    assertions.expect_equal(len(results), 2)
    assertions.expect_true(
        bool(builder.calls), reason="DuckDBQueryBuilder.build_filter_query should be invoked"
    )
    recorded = builder.calls[0]
    options = recorded["options"]
    assertions.expect_true(
        isinstance(options, DuckDBQueryOptions), reason="options should be DuckDBQueryOptions"
    )
    if not isinstance(options, DuckDBQueryOptions):  # pragma: no cover - defensive
        pytest.fail("options should be DuckDBQueryOptions")
    assertions.expect_true(options.preserve_order, reason="preserve_order should be True")
    assertions.expect_equal(options.select_columns, ("c.*",))
    assertions.expect_equal(options.include_globs, None)
    assertions.expect_equal(options.exclude_globs, None)


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
    @staticmethod
    def test_include_glob_patterns(
        test_catalog: DuckDBCatalog,
        include_glob: str,
        expected_count: int,
    ) -> None:
        """Test various include glob patterns."""
        results = test_catalog.query_by_filters(
            ALL_CHUNK_IDS,
            include_globs=[include_glob],
        )

        assertions.expect_equal(len(results), expected_count)


def test_query_by_uri_supports_unlimited_results(tmp_path: Path) -> None:
    """Unlimited ``limit`` arguments return all matches."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    write_chunks_parquet(parquet_path)

    db_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(db_path, vectors_dir)
    safe_path = safe_sql_path(parquet_path, tmp_path)
    with duckdb.connect(str(db_path)) as connection:
        connection.sql("SELECT * FROM read_parquet(?)", params=[safe_path]).create_view(
            "chunks", replace=True
        )

    limited = catalog.query_by_uri("example.py", limit=1)
    unlimited_zero = catalog.query_by_uri("example.py", limit=0)
    unlimited_negative = catalog.query_by_uri("example.py", limit=-1)

    catalog.close()

    assertions.expect_sequence_equal([row["id"] for row in limited], [1])
    assertions.expect_sequence_equal([row["id"] for row in unlimited_zero], [1, 2])
    assertions.expect_equal(unlimited_zero, unlimited_negative)


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

    ids, results = catalog.get_embeddings_by_ids([1, 2])
    assertions.expect_sequence_equal(ids, [1])
    assertions.expect_equal(results.shape, (1, 2))
    assertions.expect_true(
        np.allclose(results[0], [0.1, 0.2]), reason="embedding should match expected values"
    )


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
    assertions.expect_equal(len(results), 1)
    assertions.expect_equal(results[0]["uri"], "src/config%file.py")


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
    assertions.expect_equal(len(results), 1)
    assertions.expect_equal(results[0]["uri"], "src/config_file.py")


def test_materialize_faiss_join_builds_table(tmp_path: Path) -> None:
    """Materializing the FAISS join hydrates a persistent table."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir(parents=True, exist_ok=True)
    chunks_parquet = vectors_dir / "chunks.parquet"
    write_chunks_parquet(chunks_parquet)

    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir(parents=True, exist_ok=True)
    idmap_parquet = faiss_dir / "faiss_idmap.parquet"
    write_idmap_parquet(idmap_parquet)

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    catalog.ensure_faiss_idmap_views(idmap_parquet)
    catalog.materialize_faiss_join()

    with duckdb.connect(str(catalog_path)) as connection:
        row = connection.execute("SELECT COUNT(*) FROM faiss_join_mat").fetchone()
        count = row[0] if row else 0
    assertions.expect_equal(count, 2)


def test_open_materialize_creates_table_and_index(tmp_path: Path) -> None:
    """Materialization builds a table and supporting index."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    write_chunks_parquet(parquet_path)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assertions.expect_equal(catalog.count_chunks(), 3)

        assertions.expect_true(
            table_exists(catalog_path, "chunks_materialized"), reason="table should exist"
        )
        assertions.expect_true(
            index_exists(catalog_path, "chunks_materialized", "idx_chunks_materialized_uri"),
            reason="index should exist",
        )

    connection = duckdb.connect(str(catalog_path))
    try:
        row = connection.execute("SELECT COUNT(*) FROM chunks_materialized").fetchone()
        row_count = row[0] if row else 0
    finally:
        connection.close()

    assertions.expect_equal(row_count, 3)


def test_materialize_creates_empty_table_when_parquet_missing(tmp_path: Path) -> None:
    """Materialization creates empty table when parquet inputs are absent."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assertions.expect_equal(catalog.count_chunks(), 0)

    assertions.expect_true(
        table_exists(catalog_path, "chunks_materialized"), reason="table should exist"
    )
    assertions.expect_true(
        index_exists(catalog_path, "chunks_materialized", "idx_chunks_materialized_uri"),
        reason="index should exist",
    )


def test_get_structure_annotations_with_ast(tmp_path: Path) -> None:
    """Test structure annotations include AST node kinds."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT
                1::BIGINT AS id,
                'src/example.py'::VARCHAR AS uri,
                0::INTEGER AS start_line,
                10::INTEGER AS end_line,
                ['sym.A']::VARCHAR[] AS symbols
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW ast_nodes AS
            SELECT
                'src/example.py'::VARCHAR AS path,
                'FunctionDef'::VARCHAR AS node_type,
                1::INTEGER AS lineno,
                4::INTEGER AS end_lineno
            """
        )
    info = catalog.get_structure_annotations([1])[1]
    assertions.expect_equal(info.uri, "src/example.py")
    assertions.expect_sequence_equal(list(info.symbol_hits), ["sym.A"])
    assertions.expect_sequence_equal(list(info.ast_node_kinds), ["FunctionDef"])
    assertions.expect_sequence_equal(list(info.cst_matches), [])


def test_get_structure_annotations_without_optional_tables(tmp_path: Path) -> None:
    """Test structure annotations work when optional tables are missing."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT
                7::BIGINT AS id,
                'src/missing.py'::VARCHAR AS uri,
                0::INTEGER AS start_line,
                1::INTEGER AS end_line,
                []::VARCHAR[] AS symbols
            """
        )
    info = catalog.get_structure_annotations([7])[7]
    assertions.expect_sequence_equal(list(info.symbol_hits), [])
    assertions.expect_sequence_equal(list(info.ast_node_kinds), [])
    assertions.expect_sequence_equal(list(info.cst_matches), [])


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

    assertions.expect_equal(len(results), expected_count)
