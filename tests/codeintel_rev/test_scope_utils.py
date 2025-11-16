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

from tests._helpers import assertions


@pytest.mark.asyncio
async def test_get_effective_scope_valid_session_id_with_scope(
    mock_application_context: ApplicationContext,
) -> None:
    """Test that valid session ID with scope returns scope."""
    # Arrange
    session_id = "test-session-123"
    scope: ScopeIn = cast("ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]})
    await mock_application_context.scope_store.set(session_id, scope)

    # Act
    result = await get_effective_scope(mock_application_context, session_id)

    # Assert
    assert result is not None
    assertions.expect_equal(dict(result), dict(scope))


@pytest.mark.asyncio
async def test_get_effective_scope_valid_session_id_without_scope(
    mock_application_context: ApplicationContext,
) -> None:
    """Test that valid session ID without scope returns None."""
    # Arrange
    session_id = "test-session-123"

    # Act
    result = await get_effective_scope(mock_application_context, session_id)

    # Assert
    assertions.expect_equal(result, None)


@pytest.mark.asyncio
async def test_get_effective_scope_none_session_id(
    mock_application_context: ApplicationContext,
) -> None:
    """Test that None session ID returns None."""
    # Act
    result = await get_effective_scope(mock_application_context, None)

    # Assert
    assertions.expect_equal(result, None)


def test_merge_scope_filters_scope_only() -> None:
    """Test that scope only returns scope fields."""
    # Arrange
    scope: ScopeIn = cast("ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]})
    explicit_params = {}

    # Act
    result = merge_scope_filters(scope, explicit_params)

    # Assert
    assertions.expect_equal(result, dict(scope))


def test_merge_scope_filters_explicit_params_only() -> None:
    """Test that explicit params only returns params."""
    # Arrange
    scope = None
    explicit_params = {"languages": ["typescript"], "include_globs": ["**/*.ts"]}

    # Act
    result = merge_scope_filters(scope, explicit_params)

    # Assert
    assertions.expect_equal(result, explicit_params)


def test_merge_scope_filters_params_override_scope() -> None:
    """Test that explicit params override scope."""
    # Arrange
    scope: ScopeIn = cast("ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]})
    explicit_params = {"include_globs": ["src/**"]}

    # Act
    result = merge_scope_filters(scope, explicit_params)

    # Assert
    assertions.expect_equal(result["include_globs"], ["src/**"])
    assertions.expect_equal(result["languages"], ["python"])


def test_merge_scope_filters_empty_scope_and_empty_params() -> None:
    """Test that empty scope and empty params returns empty dict."""
    # Arrange
    scope = None
    explicit_params = {}

    # Act
    result = merge_scope_filters(scope, explicit_params)

    # Assert
    assertions.expect_equal(result, {})


def test_merge_scope_filters_none_params_filtered_out() -> None:
    """Test that None values in explicit params are filtered out."""
    # Arrange
    scope: ScopeIn = cast("ScopeIn", {"languages": ["python"], "include_globs": ["**/*.py"]})
    explicit_params = {"include_globs": None, "exclude_globs": None}

    # Act
    result = merge_scope_filters(scope, explicit_params)

    # Assert
    assertions.expect_equal(result["languages"], ["python"])
    assertions.expect_equal(result["include_globs"], ["**/*.py"])
    assertions.expect_false(
        "exclude_globs" in result, reason="exclude_globs should be filtered out"
    )


def test_apply_path_filters_include_globs_python_files_only() -> None:
    """Test that include globs filter to Python files only."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "README.md"]
    include_globs = ["**/*.py"]
    exclude_globs = []

    # Act
    result = apply_path_filters(paths, include_globs, exclude_globs)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py"])


def test_apply_path_filters_exclude_globs_removes_test_files() -> None:
    """Test that exclude globs remove test files."""
    # Arrange
    paths = ["src/main.py", "tests/test_main.py", "src/utils.py"]
    include_globs = ["**/*.py"]
    exclude_globs = ["**/test_*"]

    # Act
    result = apply_path_filters(paths, include_globs, exclude_globs)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/utils.py"])


def test_apply_path_filters_both_include_and_exclude() -> None:
    """Test that both include and exclude filters are applied."""
    # Arrange
    paths = ["src/main.py", "tests/test_main.py", "src/utils.py", "docs/README.md"]
    include_globs = ["**/*.py"]
    exclude_globs = ["**/test_*"]

    # Act
    result = apply_path_filters(paths, include_globs, exclude_globs)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/utils.py"])


def test_apply_path_filters_empty_globs_returns_all_paths() -> None:
    """Test that empty globs return all paths."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "README.md"]
    include_globs = []
    exclude_globs = []

    # Act
    result = apply_path_filters(paths, include_globs, exclude_globs)

    # Assert
    assertions.expect_sequence_equal(result, paths)


def test_apply_path_filters_empty_include_globs_with_exclude() -> None:
    """Test that empty include globs means include all (except excludes)."""
    # Arrange
    paths = ["src/main.py", "tests/test_main.py", "src/utils.py"]
    include_globs = []
    exclude_globs = ["**/test_*"]

    # Act
    result = apply_path_filters(paths, include_globs, exclude_globs)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/utils.py"])


def test_apply_path_filters_case_sensitive_markdown_matching() -> None:
    """Ensure markdown glob excludes uppercase filenames when expected."""
    paths = ["README.MD", "docs/guide.md"]
    include_globs = ["**/*.md"]

    result = apply_path_filters(paths, include_globs, [])

    assertions.expect_sequence_equal(result, ["docs/guide.md"])


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
def test_apply_path_filters_parametrized(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    expected: list[str],
) -> None:
    """Parametrized test for path filtering."""
    result = apply_path_filters(paths, include_globs, exclude_globs)
    assertions.expect_sequence_equal(result, expected)


def test_apply_language_filter_python_language_only() -> None:
    """Test that Python language returns only .py and .pyi files."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "README.md", "src/types.pyi"]
    languages = ["python"]

    # Act
    result = apply_language_filter(paths, languages)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/types.pyi"])


def test_apply_language_filter_multiple_languages() -> None:
    """Test that multiple languages return matching extensions."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "src/app.tsx", "README.md"]
    languages = ["python", "typescript"]

    # Act
    result = apply_language_filter(paths, languages)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/app.ts", "src/app.tsx"])


def test_apply_language_filter_unknown_language_returns_empty() -> None:
    """Test that unknown language returns empty list."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "README.md"]
    languages = ["cobol"]

    # Act
    result = apply_language_filter(paths, languages)

    # Assert
    assertions.expect_equal(result, [])


def test_apply_language_filter_empty_languages_returns_all_paths() -> None:
    """Test that empty languages list returns all paths."""
    # Arrange
    paths = ["src/main.py", "src/app.ts", "README.md"]
    languages = []

    # Act
    result = apply_language_filter(paths, languages)

    # Assert
    assertions.expect_sequence_equal(result, paths)


def test_apply_language_filter_case_insensitive_language_names() -> None:
    """Test that language names are case-insensitive."""
    # Arrange
    paths = ["src/main.py", "src/app.ts"]
    languages = ["Python", "TypeScript"]

    # Act
    result = apply_language_filter(paths, languages)

    # Assert
    assertions.expect_sequence_equal(result, ["src/main.py", "src/app.ts"])


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
def test_apply_language_filter_parametrized(
    paths: list[str], languages: list[str], expected: list[str]
) -> None:
    """Parametrized test for language filtering."""
    result = apply_language_filter(paths, languages)
    assertions.expect_sequence_equal(result, expected)


def test_path_matches_glob_simple_glob_matches_suffix() -> None:
    """Test that simple glob matches suffix."""
    assertions.expect_true(path_matches_glob("test.py", "*.py"), reason="test.py should match *.py")
    assertions.expect_false(
        path_matches_glob("test.ts", "*.py"), reason="test.ts should not match *.py"
    )


def test_path_matches_glob_recursive_glob_matches_nested_paths() -> None:
    """Test that recursive glob matches nested paths."""
    assertions.expect_true(
        path_matches_glob("src/utils/helpers.py", "**/*.py"),
        reason="nested .py should match **/*.py",
    )
    assertions.expect_false(
        path_matches_glob("README.md", "**/*.py"), reason="README.md should not match **/*.py"
    )


def test_path_matches_glob_directory_prefix_matches() -> None:
    """Test that directory prefix matches."""
    assertions.expect_true(
        path_matches_glob("src/main.py", "src/**"), reason="src/main.py should match src/**"
    )
    assertions.expect_false(
        path_matches_glob("lib/util.py", "src/**"), reason="lib/util.py should not match src/**"
    )


def test_path_matches_glob_windows_paths_normalized() -> None:
    """Test that Windows paths are normalized correctly."""
    assertions.expect_true(
        path_matches_glob("src\\main.py", "src/**"), reason="Windows path should match src/**"
    )
    assertions.expect_true(
        path_matches_glob("src\\main.py", "**/*.py"), reason="Windows path should match **/*.py"
    )


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
def test_path_matches_glob_parametrized(path: str, pattern: str, *, expected: bool) -> None:
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
    assertions.expect_equal(result, expected)
