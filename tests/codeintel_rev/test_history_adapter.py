"""Unit tests for history adapter with exception-based error handling.

Tests verify that blame_range and file_history raise appropriate exceptions
on error conditions.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import git.exc
import pytest
from codeintel_rev.errors import GitOperationError, PathNotFoundError
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters.history import blame_range, file_history

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
        Mock ApplicationContext with repo_root and async_git_client.
    """
    from codeintel_rev.app.config_context import ResolvedPaths

    context = Mock()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create test files
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text('def main():\n    print("hello")\n')
    (repo_root / "README.md").write_text("# Documentation\n")

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
        coderank_vectors_dir=repo_root / "data" / "coderank_vectors",
        coderank_faiss_index=repo_root / "data" / "faiss" / "coderank.faiss",
        warp_index_dir=repo_root / "indexes" / "warp_xtr",
    )
    context.paths = paths

    # Mock async_git_client
    context.async_git_client = AsyncMock()

    return context


async def test_blame_range_success(mock_context: Mock) -> None:
    """Test blame_range returns blame entries on success."""
    mock_context.async_git_client.blame_range.return_value = [
        {
            "line": 1,
            "author": "Test Author",
            "email": "test@example.com",
            "sha": "abc123",
            "date": "2024-01-01T00:00:00Z",
        }
    ]

    result = await blame_range(mock_context, "src/main.py", 1, 2)

    assert "blame" in result
    assert len(result["blame"]) == 1
    assert result["blame"][0]["line"] == 1


async def test_blame_range_path_outside_repository(mock_context: Mock) -> None:
    """Test blame_range raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        await blame_range(mock_context, "../../etc/passwd", 1, 10)


async def test_blame_range_file_not_found(mock_context: Mock) -> None:
    """Test blame_range raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        await blame_range(mock_context, "nonexistent.py", 1, 10)


async def test_blame_range_git_command_error(mock_context: Mock) -> None:
    """Test blame_range raises GitOperationError when Git command fails."""
    mock_context.async_git_client.blame_range.side_effect = git.exc.GitCommandError(
        "blame", "Git command failed"
    )

    with pytest.raises(GitOperationError, match="Git blame failed") as exc_info:
        await blame_range(mock_context, "src/main.py", 1, 10)

    exc = exc_info.value
    assert exc.context["path"] == "src/main.py"
    assert exc.context["git_command"] == "blame"


async def test_file_history_success(mock_context: Mock) -> None:
    """Test file_history returns commit history on success."""
    mock_context.async_git_client.file_history.return_value = [
        {
            "sha": "abc123",
            "full_sha": "abc123def456",
            "author": "Test Author",
            "email": "test@example.com",
            "date": "2024-01-01T00:00:00Z",
            "message": "Initial commit",
        }
    ]

    result = await file_history(mock_context, "src/main.py", limit=10)

    assert "commits" in result
    assert len(result["commits"]) == 1
    assert result["commits"][0]["sha"] == "abc123"


async def test_file_history_path_outside_repository(mock_context: Mock) -> None:
    """Test file_history raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        await file_history(mock_context, "../../etc/passwd", limit=10)


async def test_file_history_file_not_found(mock_context: Mock) -> None:
    """Test file_history raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        await file_history(mock_context, "nonexistent.py", limit=10)


async def test_file_history_git_command_error(mock_context: Mock) -> None:
    """Test file_history raises GitOperationError when Git command fails."""
    mock_context.async_git_client.file_history.side_effect = git.exc.GitCommandError(
        "log", "Git command failed"
    )

    with pytest.raises(GitOperationError, match="Git log failed") as exc_info:
        await file_history(mock_context, "src/main.py", limit=10)

    exc = exc_info.value
    assert exc.context["path"] == "src/main.py"
    assert exc.context["git_command"] == "log"
