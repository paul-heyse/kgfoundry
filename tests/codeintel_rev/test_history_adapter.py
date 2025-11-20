"""Unit tests for history adapter using in-memory integration harness."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import git.exc
import pytest
from codeintel_rev.errors import GitOperationError, PathNotFoundError
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters.history import blame_range, file_history

from tests._helpers import assertions
from tests._helpers.adapters import InMemoryCommit
from tests._helpers.integration import (
    AdapterSeedConfig,
    IntegrationHarness,
    build_harness_with_adapters,
)

pytestmark = pytest.mark.asyncio


def _seed_commits() -> list[InMemoryCommit]:
    return [
        InMemoryCommit(
            hexsha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            summary="Initial commit",
        )
    ]


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Harness with in-memory history adapter and seeded repo.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.

    Yields
    ------
    IntegrationHarness
        Harness containing ApplicationContext and in-memory history adapter.
    """
    files = {"src/main.py": 'def main():\n    print("hello")\n', "README.md": "# Docs\n"}
    commits = _seed_commits()
    harness = build_harness_with_adapters(
        tmp_path,
        files=files,
        seed_config=AdapterSeedConfig(
            history_map={"src/main.py": commits},
            blame_map={"src/main.py": [(commits[0], [1, 2, 3])]},
        ),
    )
    async_client = harness.history_adapter
    if async_client is not None:
        harness.context = harness.context.with_overrides(async_git_client=async_client)
    try:
        yield harness
    finally:
        harness.close()


async def test_blame_range_success(harness: IntegrationHarness) -> None:
    """Test blame_range returns blame entries on success."""
    result = await blame_range(harness.context, "src/main.py", 1, 2)
    assertions.expect_in("blame", result)
    assertions.expect_equal(len(result["blame"]), 2)
    assertions.expect_equal(result["blame"][0]["line"], 1)


async def test_blame_range_path_outside_repository(harness: IntegrationHarness) -> None:
    """Test blame_range raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        await blame_range(harness.context, "../../etc/passwd", 1, 10)


async def test_blame_range_file_not_found(harness: IntegrationHarness) -> None:
    """Test blame_range raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        await blame_range(harness.context, "nonexistent.py", 1, 10)


async def test_blame_range_git_command_error(harness: IntegrationHarness) -> None:
    """Test blame_range raises GitOperationError when Git command fails."""
    history_adapter = harness.history_adapter
    assertions.expect_true(history_adapter is not None)
    if history_adapter is None:  # pragma: no cover - defensive
        return
    history_adapter.repo.set_blame_error("src/main.py", git.exc.GitCommandError("blame", "fail"))
    with pytest.raises(GitOperationError, match="Git blame failed") as exc_info:
        await blame_range(harness.context, "src/main.py", 1, 10)

    exc = exc_info.value
    assertions.expect_equal(exc.context["path"], "src/main.py")
    assertions.expect_equal(exc.context["git_command"], "blame")
    # reset error to avoid leaking to other tests
    history_adapter.repo.set_blame_result("src/main.py", [])


async def test_file_history_success(harness: IntegrationHarness) -> None:
    """Test file_history returns commit history on success."""
    result = await file_history(harness.context, "src/main.py", limit=10)
    assertions.expect_in("commits", result)
    assertions.expect_equal(len(result["commits"]), 1)
    assertions.expect_true(result["commits"][0]["sha"].startswith("abc123"))


async def test_file_history_path_outside_repository(harness: IntegrationHarness) -> None:
    """Test file_history raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        await file_history(harness.context, "../../etc/passwd", limit=10)


async def test_file_history_file_not_found(harness: IntegrationHarness) -> None:
    """Test file_history raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        await file_history(harness.context, "nonexistent.py", limit=10)


async def test_file_history_git_command_error(harness: IntegrationHarness) -> None:
    """Test file_history raises GitOperationError when Git command fails."""
    history_adapter = harness.history_adapter
    assertions.expect_true(history_adapter is not None)
    if history_adapter is None:  # pragma: no cover - defensive
        return
    history_adapter.repo.set_history_error("src/main.py", git.exc.GitCommandError("log", "fail"))

    with pytest.raises(GitOperationError, match="Git log failed") as exc_info:
        await file_history(harness.context, "src/main.py", limit=10)

    exc = exc_info.value
    assertions.expect_equal(exc.context["path"], "src/main.py")
    assertions.expect_equal(exc.context["git_command"], "log")
