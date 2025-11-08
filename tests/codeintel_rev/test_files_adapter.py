"""Unit tests for files adapter with scope filtering.

Tests verify that list_paths correctly applies session scope filters
(include_globs, exclude_globs, languages) and respects explicit parameter precedence.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from codeintel_rev.errors import (
    FileReadError,
    InvalidLineRangeError,
    PathNotDirectoryError,
    PathNotFoundError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters.files import list_paths, open_file
from codeintel_rev.mcp_server.schemas import ScopeIn

pytestmark = pytest.mark.asyncio


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
    from codeintel_rev.app.config_context import ResolvedPaths

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

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
    )
    context.paths = paths

    return context


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
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=scope),
    ):
        result = await list_paths(mock_context, path=None, max_results=100)

        # Verify only Python files are returned
        assert "items" in result
        items = result["items"]
        assert isinstance(items, list)
        assert len(items) > 0

        # All returned files should be Python files
        paths_list = [item.get("path", "") for item in items]
        assert all(path.endswith(".py") for path in paths_list if path)
        # Should not include TypeScript or Markdown files
        assert not any(path.endswith(".ts") for path in paths_list if path)
        assert not any(path.endswith(".md") for path in paths_list if path)


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
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=scope),
    ):
        result = await list_paths(mock_context, path=None, max_results=100)

        # Verify only Python files are returned
        assert "items" in result
        items = result["items"]
        assert isinstance(items, list)
        assert len(items) > 0

        # All returned files should be Python files
        paths_list = [item.get("path", "") for item in items]
        assert all(path.endswith(".py") for path in paths_list if path)
        # Should not include TypeScript files
        assert not any(path.endswith(".ts") for path in paths_list if path)


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
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=None),
    ):
        response = await list_paths(mock_context)

    returned_paths = {item["path"] for item in response["items"]}
    assert "src/main.py" in returned_paths
    assert ".git/HEAD" not in returned_paths
    assert ".venv/pyvenv.cfg" not in returned_paths
    assert "node_modules/pkg/index.js" not in returned_paths
    assert "src/module.pyc" not in returned_paths
    assert "src/__pycache__/module.pyc" not in returned_paths


# ==================== open_file Tests ====================


def test_open_file_success(mock_context: Mock) -> None:
    """Test open_file returns file content on success."""
    result = open_file(mock_context, "README.md")

    assert result["path"] == "README.md"
    assert "content" in result
    assert "# Documentation" in result["content"]
    assert result["lines"] > 0
    assert result["size"] > 0


def test_open_file_with_line_range(mock_context: Mock) -> None:
    """Test open_file slices content by line range."""
    result = open_file(mock_context, "src/main.py", start_line=1, end_line=1)

    assert result["path"] == "src/main.py"
    assert "def main():" in result["content"]
    assert result["lines"] == 1


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
    assert exc.context["path"] == "README.md"
    assert exc.context["start_line"] == 0
    assert exc.context["end_line"] == 10


# ==================== list_paths Error Tests ====================


async def test_list_paths_path_not_found(mock_context: Mock) -> None:
    """Test list_paths raises PathNotFoundError for nonexistent paths."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=None),
        pytest.raises(PathNotFoundError, match="Path not found"),
    ):
        await list_paths(mock_context, path="nonexistent")


async def test_list_paths_path_outside_repository(mock_context: Mock) -> None:
    """Test list_paths raises PathOutsideRepositoryError for paths outside repo."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=None),
        pytest.raises(PathOutsideRepositoryError, match="escapes"),
    ):
        await list_paths(mock_context, path="../../etc")


async def test_list_paths_path_is_file(mock_context: Mock) -> None:
    """Test list_paths raises PathNotDirectoryError when path is a file, not directory."""
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.files.get_session_id",
            return_value="test-session-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.files.get_effective_scope", return_value=None),
        pytest.raises(PathNotDirectoryError, match="Path is not a directory"),
    ):
        await list_paths(mock_context, path="README.md")
