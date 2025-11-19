"""Unit tests for files adapter with scope filtering.

Tests verify that list_paths correctly applies session scope filters
(include_globs, exclude_globs, languages) and respects explicit parameter precedence.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.errors import (
    FileReadError,
    InvalidLineRangeError,
    PathNotDirectoryError,
    PathNotFoundError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters.files import list_paths, open_file
from codeintel_rev.mcp_server.schemas import ScopeIn

from tests._helpers import assertions
from tests._helpers.settings import build_app_config_for_repo


@pytest.fixture
def mock_context(tmp_path: Path) -> Mock:
    """Create a mock ApplicationContext for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test files.

    Returns
    -------
    Mock
        Mock ApplicationContext with repo_root and paths.
    """
    context = Mock()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create test files
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text('def main():\n    print("hello")\n')
    (repo_root / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (repo_root / "src" / "app.ts").write_text('function app() {\n    console.log("hello");\n}\n')
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")
    (repo_root / "README.md").write_text("# Documentation\n")

    app_config = build_app_config_for_repo(repo_root)
    context.app_config = app_config
    context.paths = resolve_application_paths(app_config)

    return context


@pytest.mark.asyncio
async def test_list_paths_with_scope_globs(mock_context: Mock) -> None:
    """Test that list_paths applies scope glob filters.

    Verifies that when session scope has include_globs, only files
    matching those patterns are returned.
    """
    scope: ScopeIn = {"include_globs": ["**/*.py"]}

    # Mock session scope retrieval
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-123",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=scope,
        ),
    ):
        result = await list_paths(mock_context, path=None, max_results=100)

        # Verify only Python files are returned
        assertions.expect_in("items", result)
        items = result["items"]
        assertions.expect_true(isinstance(items, list), reason="items should be a list")
        assertions.expect_true(len(items) > 0, reason="should have items")

        # All returned files should be Python files
        paths_list = [item.get("path", "") for item in items]
        assertions.expect_true(
            all(path.endswith(".py") for path in paths_list if path),
            reason="all paths should end with .py",
        )
        # Should not include TypeScript or Markdown files
        assertions.expect_false(
            any(path.endswith(".ts") for path in paths_list if path),
            reason="should not include .ts files",
        )
        assertions.expect_false(
            any(path.endswith(".md") for path in paths_list if path),
            reason="should not include .md files",
        )


@pytest.mark.asyncio
async def test_list_paths_with_scope_language(mock_context: Mock) -> None:
    """Test that list_paths applies scope language filters.

    Verifies that when session scope has languages, only files
    matching those language extensions are returned.
    """
    scope: ScopeIn = {"languages": ["python"]}

    # Mock session scope retrieval
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-123",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=scope,
        ),
    ):
        result = await list_paths(mock_context, path=None, max_results=100)

        # Verify only Python files are returned
        assertions.expect_in("items", result)
        items = result["items"]
        assertions.expect_true(isinstance(items, list), reason="items should be a list")
        assertions.expect_true(len(items) > 0, reason="should have items")

        # All returned files should be Python files
        paths_list = [item.get("path", "") for item in items]
        assertions.expect_true(
            all(path.endswith(".py") for path in paths_list if path),
            reason="all paths should end with .py",
        )
    # Should not include TypeScript files
    assertions.expect_false(
        any(path.endswith(".ts") for path in paths_list if path),
        reason="should not include .ts files",
    )


@pytest.mark.asyncio
async def test_list_paths_explicit_languages_override_scope(mock_context: Mock) -> None:
    """Explicit languages parameter overrides scoped languages."""
    scope: ScopeIn = {"languages": ["python"]}

    # Mock session scope retrieval but override languages via parameter
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-lang-override",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=scope,
        ),
    ):
        result = await list_paths(
            mock_context,
            path=None,
            max_results=100,
            languages=["typescript"],
        )

    assertions.expect_in("items", result)
    items = result["items"]
    assertions.expect_true(isinstance(items, list), reason="items should be a list")
    assertions.expect_true(bool(items), reason="should have items")
    paths_list = [item.get("path", "") for item in items]
    assertions.expect_true(
        all(path.endswith(".ts") for path in paths_list if path),
        reason="all paths should end with .ts",
    )
    assertions.expect_in("src/app.ts", paths_list)


@pytest.mark.asyncio
async def test_list_paths_excludes_default_directories(mock_context: Mock) -> None:
    """Default exclusion globs filter VCS, virtualenv, and cache paths."""
    repo_root = mock_context.paths.repo_root
    (repo_root / ".git").mkdir()
    (repo_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (repo_root / ".venv").mkdir()
    (repo_root / ".venv" / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")
    (repo_root / "node_modules").mkdir()
    (repo_root / "node_modules" / "pkg").mkdir(parents=True, exist_ok=True)
    (repo_root / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports = {};\n", encoding="utf-8"
    )
    (repo_root / "src" / "__pycache__").mkdir()
    (repo_root / "src" / "__pycache__" / "module.pyc").write_bytes(b"cache")
    (repo_root / "src" / "module.pyc").write_bytes(b"compiled")

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="default-scope",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ),
    ):
        response = await list_paths(mock_context)

    returned_paths = {item["path"] for item in response["items"]}
    assertions.expect_in("src/main.py", returned_paths)
    assertions.expect_false(".git/HEAD" in returned_paths, reason="should exclude .git files")
    assertions.expect_false(
        ".venv/pyvenv.cfg" in returned_paths, reason="should exclude .venv files"
    )
    assertions.expect_false(
        "node_modules/pkg/index.js" in returned_paths, reason="should exclude node_modules"
    )
    assertions.expect_false("src/module.pyc" in returned_paths, reason="should exclude .pyc files")
    assertions.expect_false(
        "src/__pycache__/module.pyc" in returned_paths, reason="should exclude __pycache__"
    )


# ==================== open_file Tests ====================


def test_open_file_success(mock_context: Mock) -> None:
    """Test open_file returns file content on success."""
    result = open_file(mock_context, "README.md")

    assertions.expect_equal(result["path"], "README.md")
    assertions.expect_in("content", result)
    assertions.expect_in("# Documentation", result["content"])
    assertions.expect_true(result["lines"] > 0, reason="lines should be positive")
    assertions.expect_true(result["size"] > 0, reason="size should be positive")


def test_open_file_with_line_range(mock_context: Mock) -> None:
    """Test open_file slices content by line range."""
    result = open_file(mock_context, "src/main.py", start_line=1, end_line=1)

    assertions.expect_equal(result["path"], "src/main.py")
    assertions.expect_in("def main():", result["content"])
    assertions.expect_equal(result["lines"], 1)


def test_open_file_path_outside_repository(mock_context: Mock) -> None:
    """Test open_file raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        open_file(mock_context, "../../etc/passwd")


def test_open_file_not_found(mock_context: Mock) -> None:
    """Test open_file raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        open_file(mock_context, "nonexistent.py")


def test_open_file_not_a_file(mock_context: Mock) -> None:
    """Test open_file raises PathNotFoundError when path is a directory."""
    with pytest.raises(PathNotFoundError, match="Not a file"):
        open_file(mock_context, "src")


def test_open_file_binary_file(mock_context: Mock) -> None:
    """Test open_file raises FileReadError for binary files."""
    # Create a binary file
    binary_file = mock_context.paths.repo_root / "binary.bin"
    binary_file.write_bytes(b"\xff\xfe\x00\x01")

    with pytest.raises(FileReadError, match="Binary file or encoding error"):
        open_file(mock_context, "binary.bin")


def test_open_file_invalid_start_line(mock_context: Mock) -> None:
    """Test open_file raises InvalidLineRangeError for invalid start_line."""
    with pytest.raises(InvalidLineRangeError, match="start_line must be a positive integer"):
        open_file(mock_context, "README.md", start_line=0)

    with pytest.raises(InvalidLineRangeError, match="start_line must be a positive integer"):
        open_file(mock_context, "README.md", start_line=-1)


def test_open_file_invalid_end_line(mock_context: Mock) -> None:
    """Test open_file raises InvalidLineRangeError for invalid end_line."""
    with pytest.raises(InvalidLineRangeError, match="end_line must be a positive integer"):
        open_file(mock_context, "README.md", end_line=0)

    with pytest.raises(InvalidLineRangeError, match="end_line must be a positive integer"):
        open_file(mock_context, "README.md", end_line=-1)


def test_open_file_start_greater_than_end(mock_context: Mock) -> None:
    """Test open_file raises InvalidLineRangeError when start_line > end_line."""
    with pytest.raises(
        InvalidLineRangeError, match="start_line must be less than or equal to end_line"
    ):
        open_file(mock_context, "README.md", start_line=10, end_line=5)


def test_open_file_exception_context(mock_context: Mock) -> None:
    """Test that exceptions include proper context."""
    with pytest.raises(InvalidLineRangeError) as exc_info:
        open_file(mock_context, "README.md", start_line=0, end_line=10)

    exc = exc_info.value
    assertions.expect_equal(exc.context["path"], "README.md")
    assertions.expect_equal(exc.context["start_line"], 0)
    assertions.expect_equal(exc.context["end_line"], 10)


# ==================== list_paths Error Tests ====================


@pytest.mark.asyncio
async def test_list_paths_path_not_found(mock_context: Mock) -> None:
    """Test list_paths raises PathNotFoundError for nonexistent paths."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ),
        pytest.raises(PathNotFoundError, match="Path not found"),
    ):
        await list_paths(mock_context, path="nonexistent")


@pytest.mark.asyncio
async def test_list_paths_path_outside_repository(mock_context: Mock) -> None:
    """Test list_paths raises PathOutsideRepositoryError for paths outside repo."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ),
        pytest.raises(PathOutsideRepositoryError, match="escapes"),
    ):
        await list_paths(mock_context, path="../../etc")


@pytest.mark.asyncio
async def test_list_paths_path_is_file(mock_context: Mock) -> None:
    """Test list_paths raises PathNotDirectoryError when path is a file, not directory."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ),
        pytest.raises(PathNotDirectoryError, match="Path is not a directory"),
    ):
        await list_paths(mock_context, path="README.md")
