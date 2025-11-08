"""Unit tests for GitClient and AsyncGitClient.

Tests use mocking to avoid real Git operations, ensuring fast and reliable
test execution without filesystem dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import git.exc
import pytest
from codeintel_rev.io.git_client import AsyncGitClient, GitClient


@pytest.fixture
def mock_repo() -> Mock:
    """Create a mock GitPython Repo object.

    Returns
    -------
    Mock
        Mock git.Repo instance with git_dir attribute.
    """
    repo = Mock(spec=git.Repo)
    repo.git_dir = Path("/mock/repo/.git")
    return repo


@pytest.fixture
def mock_commit() -> Mock:
    """Create a mock GitPython Commit object.

    Returns
    -------
    Mock
        Mock git.Commit instance with author, date, and message attributes.
    """
    commit = Mock(spec=git.Commit)
    commit.hexsha = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
    commit.author.name = "John Doe"
    commit.author.email = "john@example.com"
    commit.authored_datetime = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    commit.summary = "Test commit message"
    return commit


@pytest.fixture
def git_client(tmp_path: Path) -> GitClient:
    """Create GitClient instance for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path.

    Returns
    -------
    GitClient
        GitClient instance with repo_path set to tmp_path.
    """
    return GitClient(repo_path=tmp_path)


class TestGitClientLazyInit:
    """Test lazy repository initialization."""

    def test_repo_not_created_until_access(self, git_client: GitClient) -> None:
        """Repo should not be created until first property access."""
        assert git_client._repo is None

    def test_repo_created_on_first_access(self, git_client: GitClient, mock_repo: Mock) -> None:
        """Repo should be created on first access and cached."""
        with patch("codeintel_rev.io.git_client.git.Repo", return_value=mock_repo):
            repo1 = git_client.repo
            repo2 = git_client.repo

            assert repo1 is mock_repo
            assert repo2 is mock_repo
            assert git_client._repo is mock_repo

    def test_repo_initialization_error(self, git_client: GitClient) -> None:
        """InvalidGitRepositoryError should be raised for invalid repos."""
        with (
            patch(
                "codeintel_rev.io.git_client.git.Repo",
                side_effect=git.exc.InvalidGitRepositoryError("Not a git repo"),
            ),
            pytest.raises(git.exc.InvalidGitRepositoryError),
        ):
            _ = git_client.repo


class TestGitClientBlameRange:
    """Test GitClient.blame_range method."""

    def test_blame_range_happy_path(
        self, git_client: GitClient, mock_repo: Mock, mock_commit: Mock
    ) -> None:
        """blame_range should return typed GitBlameEntry list."""
        # Setup mock blame_incremental to return (commit, [10, 11, 12])
        blame_iter = [(mock_commit, [10, 11, 12])]
        mock_repo.blame_incremental.return_value = blame_iter
        git_client._repo = mock_repo

        entries = git_client.blame_range("test.py", start_line=10, end_line=12)

        assert len(entries) == 3
        assert entries[0]["line"] == 10
        assert entries[0]["commit"] == "a1b2c3d4"
        assert entries[0]["author"] == "John Doe"
        assert entries[0]["date"] == "2024-01-15T10:30:00+00:00"
        assert entries[0]["message"] == "Test commit message"

    def test_blame_range_filters_to_requested_lines(
        self, git_client: GitClient, mock_repo: Mock, mock_commit: Mock
    ) -> None:
        """blame_range should filter to requested line range."""
        # Return lines 5-15, but request only 10-12
        blame_iter = [(mock_commit, list(range(5, 16)))]
        mock_repo.blame_incremental.return_value = blame_iter
        git_client._repo = mock_repo

        entries = git_client.blame_range("test.py", start_line=10, end_line=12)

        assert len(entries) == 3
        assert all(10 <= entry["line"] <= 12 for entry in entries)

    def test_blame_range_file_not_found(self, git_client: GitClient, mock_repo: Mock) -> None:
        """blame_range should raise FileNotFoundError for missing files."""
        mock_repo.blame_incremental.side_effect = git.exc.GitCommandError(
            "does not exist", status=128
        )
        git_client._repo = mock_repo

        with pytest.raises(FileNotFoundError, match=r"File not found: test\.py"):
            git_client.blame_range("test.py", start_line=1, end_line=10)

    def test_blame_range_git_command_error(self, git_client: GitClient, mock_repo: Mock) -> None:
        """blame_range should propagate GitCommandError for other errors."""
        mock_repo.blame_incremental.side_effect = git.exc.GitCommandError(
            "Permission denied", status=1
        )
        git_client._repo = mock_repo

        with pytest.raises(git.exc.GitCommandError):
            git_client.blame_range("test.py", start_line=1, end_line=10)

    @pytest.mark.parametrize(
        ("error_msg", "should_raise_file_not_found"),
        [
            ("does not exist", True),
            ("bad file", True),
            ("Permission denied", False),
            ("Not a git repository", False),
        ],
    )
    def test_blame_range_error_handling(
        self,
        git_client: GitClient,
        mock_repo: Mock,
        error_msg: str,
        *,  # Force keyword-only args after this
        should_raise_file_not_found: bool,
    ) -> None:
        """blame_range should handle different error messages correctly."""
        mock_repo.blame_incremental.side_effect = git.exc.GitCommandError(error_msg, status=128)
        git_client._repo = mock_repo

        if should_raise_file_not_found:
            with pytest.raises(FileNotFoundError):
                git_client.blame_range("test.py", start_line=1, end_line=10)
        else:
            with pytest.raises(git.exc.GitCommandError):
                git_client.blame_range("test.py", start_line=1, end_line=10)

    def test_blame_range_unicode_author(
        self, git_client: GitClient, mock_repo: Mock, mock_commit: Mock
    ) -> None:
        """blame_range should handle Unicode author names."""
        mock_commit.author.name = "José García"
        blame_iter = [(mock_commit, [10])]
        mock_repo.blame_incremental.return_value = blame_iter
        git_client._repo = mock_repo

        entries = git_client.blame_range("test.py", start_line=10, end_line=10)

        assert entries[0]["author"] == "José García"


class TestGitClientFileHistory:
    """Test GitClient.file_history method."""

    @pytest.mark.usefixtures("_mock_commit")
    def test_file_history_happy_path(self, git_client: GitClient, mock_repo: Mock) -> None:
        """file_history should return commit list."""
        # Create multiple mock commits
        commits = []
        for i in range(3):
            commit = Mock(spec=git.Commit)
            commit.hexsha = f"{i:040d}"  # 40-digit hex
            commit.author.name = f"Author {i}"
            commit.author.email = f"author{i}@example.com"
            commit.authored_datetime = datetime(2024, 1, 15 + i, 10, 30, 0, tzinfo=UTC)
            commit.summary = f"Commit {i}"
            commits.append(commit)

        mock_repo.iter_commits.return_value = iter(commits)
        git_client._repo = mock_repo

        history = git_client.file_history("test.py", limit=10)

        assert len(history) == 3
        assert history[0]["sha"] == "00000000"
        assert history[0]["full_sha"] == "0" * 40
        assert history[0]["author"] == "Author 0"
        assert history[0]["email"] == "author0@example.com"
        assert history[0]["message"] == "Commit 0"

    def test_file_history_empty_history(self, git_client: GitClient, mock_repo: Mock) -> None:
        """file_history should return empty list for files with no history."""
        mock_repo.iter_commits.return_value = iter([])
        git_client._repo = mock_repo

        history = git_client.file_history("test.py", limit=50)

        assert history == []

    def test_file_history_respects_limit(self, git_client: GitClient, mock_repo: Mock) -> None:
        """file_history should respect limit parameter."""
        # Create 10 mock commits
        commits = []
        for i in range(10):
            commit = Mock(spec=git.Commit)
            commit.hexsha = f"{i:040d}"
            commit.author.name = f"Author {i}"
            commit.author.email = f"author{i}@example.com"
            commit.authored_datetime = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
            commit.summary = f"Commit {i}"
            commits.append(commit)

        # Only return first 5 commits (simulating max_count behavior)
        mock_repo.iter_commits.return_value = iter(commits[:5])
        git_client._repo = mock_repo

        history = git_client.file_history("test.py", limit=5)

        assert len(history) == 5
        # Verify iter_commits was called with max_count=5
        mock_repo.iter_commits.assert_called_once_with(rev="HEAD", paths="test.py", max_count=5)

    def test_file_history_file_not_found(self, git_client: GitClient, mock_repo: Mock) -> None:
        """file_history should raise FileNotFoundError for missing files."""
        mock_repo.iter_commits.side_effect = git.exc.GitCommandError("does not exist", status=128)
        git_client._repo = mock_repo

        with pytest.raises(FileNotFoundError, match=r"File not found: test\.py"):
            git_client.file_history("test.py", limit=50)

    def test_file_history_git_command_error(self, git_client: GitClient, mock_repo: Mock) -> None:
        """file_history should propagate GitCommandError for other errors."""
        mock_repo.iter_commits.side_effect = git.exc.GitCommandError("Permission denied", status=1)
        git_client._repo = mock_repo

        with pytest.raises(git.exc.GitCommandError):
            git_client.file_history("test.py", limit=50)


class TestAsyncGitClient:
    """Test AsyncGitClient wrapper."""

    @pytest.mark.asyncio
    async def test_async_blame_range_calls_sync_client(
        self, git_client: GitClient, mock_repo: Mock, mock_commit: Mock
    ) -> None:
        """Async blame_range should call sync client via asyncio.to_thread."""
        blame_iter = [(mock_commit, [10, 11])]
        mock_repo.blame_incremental.return_value = blame_iter
        git_client._repo = mock_repo

        async_client = AsyncGitClient(git_client)
        entries = await async_client.blame_range("test.py", start_line=10, end_line=11)

        assert len(entries) == 2
        assert entries[0]["line"] == 10
        assert entries[0]["author"] == "John Doe"

    @pytest.mark.asyncio
    async def test_async_file_history_calls_sync_client(
        self, git_client: GitClient, mock_repo: Mock, mock_commit: Mock
    ) -> None:
        """Async file_history should call sync client via asyncio.to_thread."""
        mock_repo.iter_commits.return_value = iter([mock_commit])
        git_client._repo = mock_repo

        async_client = AsyncGitClient(git_client)
        commits = await async_client.file_history("test.py", limit=5)

        assert len(commits) == 1
        assert commits[0]["author"] == "John Doe"

    @pytest.mark.asyncio
    async def test_async_blame_range_propagates_errors(
        self, git_client: GitClient, mock_repo: Mock
    ) -> None:
        """Async blame_range should propagate FileNotFoundError."""
        mock_repo.blame_incremental.side_effect = git.exc.GitCommandError(
            "does not exist", status=128
        )
        git_client._repo = mock_repo

        async_client = AsyncGitClient(git_client)

        with pytest.raises(FileNotFoundError):
            await async_client.blame_range("test.py", start_line=1, end_line=10)

    @pytest.mark.asyncio
    async def test_async_file_history_propagates_errors(
        self, git_client: GitClient, mock_repo: Mock
    ) -> None:
        """Async file_history should propagate FileNotFoundError."""
        mock_repo.iter_commits.side_effect = git.exc.GitCommandError("does not exist", status=128)
        git_client._repo = mock_repo

        async_client = AsyncGitClient(git_client)

        with pytest.raises(FileNotFoundError):
            await async_client.file_history("test.py", limit=50)
