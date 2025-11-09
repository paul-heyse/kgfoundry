"""Unit tests for scope utilities.

Tests scope retrieval, merging, and filtering functions with comprehensive
edge case coverage.
"""

from __future__ import annotations

from typing import cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.scope_utils import (
    apply_language_filter,
    apply_path_filters,
    get_effective_scope,
    merge_scope_filters,
    path_matches_glob,
)


class TestGetEffectiveScope:
    """Tests for get_effective_scope function."""

    @pytest.mark.asyncio
    async def test_valid_session_id_with_scope(
        self, mock_application_context: ApplicationContext
    ) -> None:
        """Test that valid session ID with scope returns scope."""
        # Arrange
        session_id = "test-session-123"
        scope: ScopeIn = cast(
            "ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]}
        )
        await mock_application_context.scope_store.set(session_id, scope)

        # Act
        result = await get_effective_scope(mock_application_context, session_id)

        # Assert
        assert result == scope

    @pytest.mark.asyncio
    async def test_valid_session_id_without_scope(
        self, mock_application_context: ApplicationContext
    ) -> None:
        """Test that valid session ID without scope returns None."""
        # Arrange
        session_id = "test-session-123"

        # Act
        result = await get_effective_scope(mock_application_context, session_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_none_session_id(
        self, mock_application_context: ApplicationContext
    ) -> None:
        """Test that None session ID returns None."""
        # Act
        result = await get_effective_scope(mock_application_context, None)

        # Assert
        assert result is None


class TestMergeScopeFilters:
    """Tests for merge_scope_filters function."""

    def test_scope_only(self) -> None:
        """Test that scope only returns scope fields."""
        # Arrange
        scope: ScopeIn = cast(
            "ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]}
        )
        explicit_params = {}

        # Act
        result = merge_scope_filters(scope, explicit_params)

        # Assert
        assert result == scope

    def test_explicit_params_only(self) -> None:
        """Test that explicit params only returns params."""
        # Arrange
        scope = None
        explicit_params = {"languages": ["typescript"], "include_globs": ["**/*.ts"]}

        # Act
        result = merge_scope_filters(scope, explicit_params)

        # Assert
        assert result == explicit_params

    def test_params_override_scope(self) -> None:
        """Test that explicit params override scope."""
        # Arrange
        scope: ScopeIn = cast(
            "ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]}
        )
        explicit_params = {"include_globs": ["src/**"]}

        # Act
        result = merge_scope_filters(scope, explicit_params)

        # Assert
        assert result["include_globs"] == ["src/**"]
        assert result["languages"] == ["python"]

    def test_empty_scope_and_empty_params(self) -> None:
        """Test that empty scope and empty params returns empty dict."""
        # Arrange
        scope = None
        explicit_params = {}

        # Act
        result = merge_scope_filters(scope, explicit_params)

        # Assert
        assert result == {}

    def test_none_params_filtered_out(self) -> None:
        """Test that None values in explicit params are filtered out."""
        # Arrange
        scope: ScopeIn = cast(
            "ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]}
        )
        explicit_params = {"include_globs": None, "exclude_globs": None}

        # Act
        result = merge_scope_filters(scope, explicit_params)

        # Assert
        assert result["languages"] == ["python"]
        assert result["include_globs"] == ["**/*.py"]
        assert "exclude_globs" not in result


class TestApplyPathFilters:
    """Tests for apply_path_filters function."""

    def test_include_globs_python_files_only(self) -> None:
        """Test that include globs filter to Python files only."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "README.md"]
        include_globs = ["**/*.py"]
        exclude_globs = []

        # Act
        result = apply_path_filters(paths, include_globs, exclude_globs)

        # Assert
        assert result == ["src/main.py"]

    def test_exclude_globs_removes_test_files(self) -> None:
        """Test that exclude globs remove test files."""
        # Arrange
        paths = ["src/main.py", "tests/test_main.py", "src/utils.py"]
        include_globs = ["**/*.py"]
        exclude_globs = ["**/test_*"]

        # Act
        result = apply_path_filters(paths, include_globs, exclude_globs)

        # Assert
        assert result == ["src/main.py", "src/utils.py"]

    def test_both_include_and_exclude(self) -> None:
        """Test that both include and exclude filters are applied."""
        # Arrange
        paths = ["src/main.py", "tests/test_main.py", "src/utils.py", "docs/README.md"]
        include_globs = ["**/*.py"]
        exclude_globs = ["**/test_*"]

        # Act
        result = apply_path_filters(paths, include_globs, exclude_globs)

        # Assert
        assert result == ["src/main.py", "src/utils.py"]

    def test_empty_globs_returns_all_paths(self) -> None:
        """Test that empty globs return all paths."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "README.md"]
        include_globs = []
        exclude_globs = []

        # Act
        result = apply_path_filters(paths, include_globs, exclude_globs)

        # Assert
        assert result == paths

    def test_empty_include_globs_with_exclude(self) -> None:
        """Test that empty include globs means include all (except excludes)."""
        # Arrange
        paths = ["src/main.py", "tests/test_main.py", "src/utils.py"]
        include_globs = []
        exclude_globs = ["**/test_*"]

        # Act
        result = apply_path_filters(paths, include_globs, exclude_globs)

        # Assert
        assert result == ["src/main.py", "src/utils.py"]

    def test_case_sensitive_markdown_matching(self) -> None:
        """Ensure markdown glob excludes uppercase filenames when expected."""
        paths = ["README.MD", "docs/guide.md"]
        include_globs = ["**/*.md"]

        result = apply_path_filters(paths, include_globs, [])

        assert result == ["docs/guide.md"]

    @pytest.mark.parametrize(
        ("paths", "include_globs", "exclude_globs", "expected"),
        [
            (
                ["src/main.py", "src/app.ts"],
                ["**/*.py"],
                [],
                ["src/main.py"],
            ),
            (
                ["src/main.py", "tests/test_main.py"],
                ["**/*.py"],
                ["**/test_*"],
                ["src/main.py"],
            ),
            (
                ["src/main.py", "src/app.ts", "README.md"],
                [],
                [],
                ["src/main.py", "src/app.ts", "README.md"],
            ),
        ],
    )
    def test_path_filters_parametrized(
        self,
        paths: list[str],
        include_globs: list[str],
        exclude_globs: list[str],
        expected: list[str],
    ) -> None:
        """Parametrized test for path filtering."""
        result = apply_path_filters(paths, include_globs, exclude_globs)
        assert result == expected


class TestApplyLanguageFilter:
    """Tests for apply_language_filter function."""

    def test_python_language_only(self) -> None:
        """Test that Python language returns only .py and .pyi files."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "README.md", "src/types.pyi"]
        languages = ["python"]

        # Act
        result = apply_language_filter(paths, languages)

        # Assert
        assert result == ["src/main.py", "src/types.pyi"]

    def test_multiple_languages(self) -> None:
        """Test that multiple languages return matching extensions."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "src/app.tsx", "README.md"]
        languages = ["python", "typescript"]

        # Act
        result = apply_language_filter(paths, languages)

        # Assert
        assert result == ["src/main.py", "src/app.ts", "src/app.tsx"]

    def test_unknown_language_returns_empty(self) -> None:
        """Test that unknown language returns empty list."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "README.md"]
        languages = ["cobol"]

        # Act
        result = apply_language_filter(paths, languages)

        # Assert
        assert result == []

    def test_empty_languages_returns_all_paths(self) -> None:
        """Test that empty languages list returns all paths."""
        # Arrange
        paths = ["src/main.py", "src/app.ts", "README.md"]
        languages = []

        # Act
        result = apply_language_filter(paths, languages)

        # Assert
        assert result == paths

    def test_case_insensitive_language_names(self) -> None:
        """Test that language names are case-insensitive."""
        # Arrange
        paths = ["src/main.py", "src/app.ts"]
        languages = ["Python", "TypeScript"]

        # Act
        result = apply_language_filter(paths, languages)

        # Assert
        assert result == ["src/main.py", "src/app.ts"]

    @pytest.mark.parametrize(
        ("paths", "languages", "expected"),
        [
            (
                ["src/main.py", "src/app.ts"],
                ["python"],
                ["src/main.py"],
            ),
            (
                ["src/main.py", "src/app.ts", "src/app.tsx"],
                ["python", "typescript"],
                ["src/main.py", "src/app.ts", "src/app.tsx"],
            ),
            (
                ["src/main.py", "src/app.ts"],
                ["cobol"],
                [],
            ),
        ],
    )
    def test_language_filter_parametrized(
        self, paths: list[str], languages: list[str], expected: list[str]
    ) -> None:
        """Parametrized test for language filtering."""
        result = apply_language_filter(paths, languages)
        assert result == expected


class TestPathMatchesGlob:
    """Tests for path_matches_glob function."""

    def test_simple_glob_matches_suffix(self) -> None:
        """Test that simple glob matches suffix."""
        assert path_matches_glob("test.py", "*.py") is True
        assert path_matches_glob("test.ts", "*.py") is False

    def test_recursive_glob_matches_nested_paths(self) -> None:
        """Test that recursive glob matches nested paths."""
        assert path_matches_glob("src/utils/helpers.py", "**/*.py") is True
        assert path_matches_glob("README.md", "**/*.py") is False

    def test_directory_prefix_matches(self) -> None:
        """Test that directory prefix matches."""
        assert path_matches_glob("src/main.py", "src/**") is True
        assert path_matches_glob("lib/util.py", "src/**") is False

    def test_windows_paths_normalized(self) -> None:
        """Test that Windows paths are normalized correctly."""
        assert path_matches_glob("src\\main.py", "src/**") is True
        assert path_matches_glob("src\\main.py", "**/*.py") is True

    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            ("test.py", "*.py", True),
            ("test.ts", "*.py", False),
            ("src/utils/helpers.py", "**/*.py", True),
            ("README.md", "**/*.py", False),
            ("src/main.py", "src/**", True),
            ("lib/util.py", "src/**", False),
            ("src\\main.py", "src/**", True),  # Windows path
            ("src\\main.py", "**/*.py", True),  # Windows path
        ],
    )
    def test_path_matches_glob_parametrized(
        self, path: str, pattern: str, *, expected: bool
    ) -> None:
        """Parametrized test for glob matching.

        Parameters
        ----------
        path : str
            File path to test.
        pattern : str
            Glob pattern to match against.
        expected : bool
            Expected match result.
        """
        result = path_matches_glob(path, pattern)
        assert result == expected
