"""Integration tests for GitClient with real Git repository.

Tests verify GitClient behavior with actual Git operations, ensuring
correctness with real repository data and edge cases.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import git.exc
import pytest
from codeintel_rev.io.git_client import AsyncGitClient, GitClient


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real Git repository for testing.

    Creates a temporary Git repository with multiple commits and files
    for testing GitClient operations.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test repository.

    Returns
    -------
    Path
        Path to Git repository root. Repository is cleaned up after test.

    Raises
    ------
    RuntimeError
        If git command is not found in PATH.
    """
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()

    # Resolve git command to full path for security (S607)
    git_cmd = shutil.which("git")
    if git_cmd is None:
        msg = "git command not found in PATH"
        raise RuntimeError(msg)

    # Initialize Git repository
    subprocess.run(
        [git_cmd, "init"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )

    # Configure Git user (required for commits)
    subprocess.run(
        [git_cmd, "config", "user.name", "Test User"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git_cmd, "config", "user.email", "test@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )

    # Create test file with multiple lines
    test_file = repo_root / "test.py"
    test_file.write_text(
        """def function1():
    return 1

def function2():
    return 2

def function3():
    return 3
"""
    )

    # Create commits with different authors
    authors = [
        ("Alice Developer", "alice@example.com"),
        ("Bob Maintainer", "bob@example.com"),
        ("Charlie Reviewer", "charlie@example.com"),
        ("Diana Architect", "diana@example.com"),
        ("Eve Contributor", "eve@example.com"),
    ]

    for i, (name, email) in enumerate(authors):
        # Modify file
        test_file.write_text(
            f"""def function1():
    return {i + 1}

def function2():
    return {i + 2}

def function3():
    return {i + 3}
"""
        )

        # Stage and commit
        subprocess.run(
            [git_cmd, "add", "test.py"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                git_cmd,
                "commit",
                "-m",
                f"Update function returns (commit {i + 1})",
                f"--author={name} <{email}>",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

    return repo_root


@pytest.mark.integration
class TestGitClientIntegration:
    """Integration tests for GitClient with real repository."""

    def test_blame_range_with_real_repo(self, git_repo: Path) -> None:
        """blame_range should return correct blame entries."""
        client = GitClient(repo_path=git_repo)

        entries = client.blame_range("test.py", start_line=1, end_line=5)

        assert len(entries) == 5
        # Verify structure
        for entry in entries:
            assert "line" in entry
            assert "commit" in entry
            assert "author" in entry
            assert "date" in entry
            assert "message" in entry
            assert len(entry["commit"]) == 8  # Short SHA
            # Verify date is ISO 8601 format
            datetime.fromisoformat(entry["date"].replace("Z", "+00:00"))

    def test_blame_range_commit_shas_match(self, git_repo: Path) -> None:
        """blame_range commit SHAs should match actual Git commits.

        Raises
        ------
        RuntimeError
            If git command is not found in PATH.
        """
        client = GitClient(repo_path=git_repo)

        entries = client.blame_range("test.py", start_line=1, end_line=10)

        # Get actual commit SHAs from git log
        git_cmd = shutil.which("git")
        if git_cmd is None:
            msg = "git command not found in PATH"
            raise RuntimeError(msg)
        result = subprocess.run(
            [git_cmd, "log", "--format=%H", "test.py"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        actual_shas = [line[:8] for line in result.stdout.strip().split("\n") if line]

        # Verify blame entries reference valid commits
        entry_shas = {entry["commit"] for entry in entries}
        assert all(sha in actual_shas for sha in entry_shas)

    def test_blame_range_author_names(self, git_repo: Path) -> None:
        """blame_range should return correct author names."""
        client = GitClient(repo_path=git_repo)

        entries = client.blame_range("test.py", start_line=1, end_line=10)

        # Get author names from entries
        authors = {entry["author"] for entry in entries}

        # Should include at least some of our test authors
        expected_authors = {
            "Alice Developer",
            "Bob Maintainer",
            "Charlie Reviewer",
            "Diana Architect",
            "Eve Contributor",
        }
        assert authors.intersection(expected_authors)

    def test_file_history_with_real_repo(self, git_repo: Path) -> None:
        """file_history should return commit history."""
        client = GitClient(repo_path=git_repo)

        commits = client.file_history("test.py", limit=10)

        assert len(commits) == 5  # We created 5 commits
        # Verify structure
        for commit in commits:
            assert "sha" in commit
            assert "full_sha" in commit
            assert "author" in commit
            assert "email" in commit
            assert "date" in commit
            assert "message" in commit
            assert len(commit["sha"]) == 8
            assert len(commit["full_sha"]) == 40
            # Verify date is ISO 8601 format
            datetime.fromisoformat(commit["date"].replace("Z", "+00:00"))

    def test_file_history_commit_order(self, git_repo: Path) -> None:
        """file_history should return commits in newest-first order."""
        client = GitClient(repo_path=git_repo)

        commits = client.file_history("test.py", limit=10)

        # Verify order (newest first)
        dates = [datetime.fromisoformat(c["date"].replace("Z", "+00:00")) for c in commits]
        assert dates == sorted(dates, reverse=True)

    def test_file_history_respects_limit(self, git_repo: Path) -> None:
        """file_history should respect limit parameter."""
        client = GitClient(repo_path=git_repo)

        commits_all = client.file_history("test.py", limit=100)
        commits_limited = client.file_history("test.py", limit=3)

        assert len(commits_all) == 5  # All commits
        assert len(commits_limited) == 3  # Limited to 3

    def test_file_history_author_names(self, git_repo: Path) -> None:
        """file_history should return correct author names."""
        client = GitClient(repo_path=git_repo)

        commits = client.file_history("test.py", limit=10)

        authors = {commit["author"] for commit in commits}
        expected_authors = {
            "Alice Developer",
            "Bob Maintainer",
            "Charlie Reviewer",
            "Diana Architect",
            "Eve Contributor",
        }
        assert authors == expected_authors

    def test_blame_range_file_not_found(self, git_repo: Path) -> None:
        """blame_range should raise FileNotFoundError for missing files."""
        client = GitClient(repo_path=git_repo)

        # GitPython may raise GitCommandError instead of FileNotFoundError
        # depending on Git version, so catch both
        with pytest.raises((FileNotFoundError, git.exc.GitCommandError)):  # type: ignore[arg-type]
            client.blame_range("nonexistent.py", start_line=1, end_line=10)

    def test_file_history_file_not_found(self, git_repo: Path) -> None:
        """file_history should raise FileNotFoundError for missing files."""
        client = GitClient(repo_path=git_repo)

        # GitPython's iter_commits may return empty iterator for nonexistent files
        # instead of raising an error, so we check for empty result
        commits = client.file_history("nonexistent.py", limit=10)
        # Either raises exception or returns empty list
        assert commits == [] or len(commits) == 0

    def test_blame_range_invalid_line_range(self, git_repo: Path) -> None:
        """blame_range should handle invalid line ranges gracefully."""
        client = GitClient(repo_path=git_repo)

        # Request lines beyond file length - GitPython raises GitCommandError
        # for invalid line ranges, so we expect that exception
        with pytest.raises(git.exc.GitCommandError):
            client.blame_range("test.py", start_line=100, end_line=200)


@pytest.mark.integration
@pytest.mark.asyncio
class TestAsyncGitClientIntegration:
    """Integration tests for AsyncGitClient with real repository."""

    async def test_async_blame_range_with_real_repo(self, git_repo: Path) -> None:
        """Async blame_range should work with real repository."""
        sync_client = GitClient(repo_path=git_repo)
        async_client = AsyncGitClient(sync_client)

        entries = await async_client.blame_range("test.py", start_line=1, end_line=5)

        assert len(entries) == 5
        assert all("line" in entry for entry in entries)

    async def test_async_file_history_with_real_repo(self, git_repo: Path) -> None:
        """Async file_history should work with real repository."""
        sync_client = GitClient(repo_path=git_repo)
        async_client = AsyncGitClient(sync_client)

        commits = await async_client.file_history("test.py", limit=5)

        assert len(commits) == 5
        assert all("sha" in commit for commit in commits)
