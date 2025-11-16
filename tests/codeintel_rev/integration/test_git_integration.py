"""Integration tests for GitClient with real Git repository.

Tests verify GitClient behavior with actual Git operations, ensuring
correctness with real repository data and edge cases.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from git.exc import GitCommandError

from tests._helpers import assertions, constants, run_process

pytestmark = pytest.mark.integration

SHORT_SHA_LENGTH = 8
FULL_SHA_LENGTH = 40
EXPECTED_AUTHORS = {
    "Alice Developer",
    "Bob Maintainer",
    "Charlie Reviewer",
    "Diana Architect",
    "Eve Contributor",
}


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

    """
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()

    # Resolve git command to full path for security (S607)
    git_cmd = shutil.which("git")
    if git_cmd is None:
        pytest.skip("git command not found in PATH")

    # Initialize Git repository
    run_process([git_cmd, "init"], cwd=repo_root)

    # Configure Git user (required for commits)
    run_process([git_cmd, "config", "user.name", "Test User"], cwd=repo_root)
    run_process([git_cmd, "config", "user.email", "test@example.com"], cwd=repo_root)

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
        run_process([git_cmd, "add", "test.py"], cwd=repo_root)
        run_process(
            [
                git_cmd,
                "commit",
                "-m",
                f"Update function returns (commit {i + 1})",
                f"--author={name} <{email}>",
            ],
            cwd=repo_root,
        )

    return repo_root


def test_blame_range_with_real_repo(git_repo: Path) -> None:
    """blame_range should return correct blame entries."""
    client = GitClient(repo_path=git_repo)

    entries = client.blame_range("test.py", start_line=1, end_line=5)

    assertions.expect_equal(len(entries), constants.BATCH_SIZES.large)
    for entry in entries:
        for key in ("line", "commit", "author", "date", "message"):
            assertions.expect_in(key, entry)
        assertions.expect_equal(len(entry["commit"]), SHORT_SHA_LENGTH)
        datetime.fromisoformat(entry["date"].replace("Z", "+00:00"))


def test_blame_range_commit_shas_match(git_repo: Path) -> None:
    """blame_range commit SHAs should match actual Git commits."""
    client = GitClient(repo_path=git_repo)

    entries = client.blame_range("test.py", start_line=1, end_line=10)

    git_cmd = shutil.which("git")
    if git_cmd is None:
        pytest.skip("git command not found in PATH")
    output = run_process([git_cmd, "log", "--format=%H", "test.py"], cwd=git_repo)
    actual_shas = [line[:SHORT_SHA_LENGTH] for line in output.strip().splitlines() if line]

    entry_shas = {entry["commit"] for entry in entries}
    assertions.expect_true(all(sha in actual_shas for sha in entry_shas))


def test_blame_range_author_names(git_repo: Path) -> None:
    """blame_range should return correct author names."""
    client = GitClient(repo_path=git_repo)

    entries = client.blame_range("test.py", start_line=1, end_line=10)
    authors = {entry["author"] for entry in entries}
    assertions.expect_true(authors.intersection(EXPECTED_AUTHORS))


def test_file_history_with_real_repo(git_repo: Path) -> None:
    """file_history should return commit history."""
    client = GitClient(repo_path=git_repo)

    commits = client.file_history("test.py", limit=10)

    assertions.expect_equal(len(commits), constants.BATCH_SIZES.large)
    for commit in commits:
        for key in ("sha", "full_sha", "author", "email", "date", "message"):
            assertions.expect_in(key, commit)
        assertions.expect_equal(len(commit["sha"]), SHORT_SHA_LENGTH)
        assertions.expect_equal(len(commit["full_sha"]), FULL_SHA_LENGTH)
        datetime.fromisoformat(commit["date"].replace("Z", "+00:00"))


def test_file_history_commit_order(git_repo: Path) -> None:
    """file_history should return commits in newest-first order."""
    client = GitClient(repo_path=git_repo)

    commits = client.file_history("test.py", limit=10)
    dates = [datetime.fromisoformat(c["date"].replace("Z", "+00:00")) for c in commits]
    assertions.expect_sequence_equal(dates, sorted(dates, reverse=True))


def test_file_history_respects_limit(git_repo: Path) -> None:
    """file_history should respect limit parameter."""
    client = GitClient(repo_path=git_repo)

    commits_all = client.file_history("test.py", limit=100)
    commits_limited = client.file_history("test.py", limit=constants.BATCH_SIZES.small)

    assertions.expect_equal(len(commits_all), constants.BATCH_SIZES.large)
    assertions.expect_equal(len(commits_limited), constants.BATCH_SIZES.small)


def test_file_history_author_names(git_repo: Path) -> None:
    """file_history should return correct author names."""
    client = GitClient(repo_path=git_repo)

    commits = client.file_history("test.py", limit=10)
    authors = {commit["author"] for commit in commits}
    assertions.expect_equal(authors, EXPECTED_AUTHORS)


def test_blame_range_file_not_found(git_repo: Path) -> None:
    """blame_range should raise FileNotFoundError for missing files."""
    client = GitClient(repo_path=git_repo)

    allowed_exceptions: tuple[type[BaseException], ...] = (FileNotFoundError, GitCommandError)
    with pytest.raises(allowed_exceptions):
        client.blame_range("nonexistent.py", start_line=1, end_line=10)


def test_file_history_file_not_found(git_repo: Path) -> None:
    """file_history should handle missing files gracefully."""
    client = GitClient(repo_path=git_repo)

    commits = client.file_history("nonexistent.py", limit=10)
    assertions.expect_equal(len(commits), 0)


def test_blame_range_invalid_line_range(git_repo: Path) -> None:
    """blame_range should handle invalid line ranges gracefully."""
    client = GitClient(repo_path=git_repo)

    with pytest.raises(GitCommandError):
        client.blame_range("test.py", start_line=100, end_line=200)


@pytest.mark.asyncio
async def test_async_blame_range_with_real_repo(git_repo: Path) -> None:
    """Async blame_range should work with real repository."""
    sync_client = GitClient(repo_path=git_repo)
    async_client = AsyncGitClient(sync_client)

    entries = await async_client.blame_range("test.py", start_line=1, end_line=5)

    assertions.expect_equal(len(entries), constants.BATCH_SIZES.large)
    assertions.expect_true(all("line" in entry for entry in entries))


@pytest.mark.asyncio
async def test_async_file_history_with_real_repo(git_repo: Path) -> None:
    """Async file_history should work with real repository."""
    sync_client = GitClient(repo_path=git_repo)
    async_client = AsyncGitClient(sync_client)

    commits = await async_client.file_history("test.py", limit=constants.BATCH_SIZES.large)

    assertions.expect_equal(len(commits), constants.BATCH_SIZES.large)
    assertions.expect_true(all("sha" in commit for commit in commits))
