"""Load tests for concurrent adapter operations.

Tests verify that async adapters can handle high concurrency without
thread exhaustion or performance degradation.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Load tests skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)


@pytest.fixture
def mock_context(tmp_path: Path) -> Mock:
    """Create a mock ApplicationContext for load testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test files.

    Returns
    -------
    Mock
        Mock ApplicationContext with repo_root and GitClient.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create test files
    (repo_root / "src").mkdir()
    for i in range(100):
        (repo_root / "src" / f"file_{i}.py").write_text(f"def func_{i}():\n    pass\n")

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
    )

    context = Mock(spec=ApplicationContext)
    context.paths = paths
    context.git_client = Mock()
    context.async_git_client = _AsyncGitClientStub()

    return context


class _AsyncGitClientStub:
    """Async Git client stub returning deterministic blame results."""

    async def blame_range(
        self,
        *,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict]:
        del path
        return [
            {
                "line": line,
                "commit": "stub",
                "author": "LoadTest",
                "date": "2024-01-01T00:00:00Z",
                "message": f"Line {line}",
            }
            for line in range(start_line, end_line + 1)
        ]

    async def file_history(self, *, path: str, limit: int) -> list[dict]:
        del path
        return [
            {
                "sha": f"{i:04x}",
                "full_sha": f"{i:08x}",
                "author": "LoadTest",
                "email": "load@example.com",
                "date": "2024-01-01T00:00:00Z",
                "message": f"Commit {i}",
            }
            for i in range(limit)
        ]


@pytest.mark.load
@pytest.mark.asyncio
async def test_concurrent_list_paths(mock_context: Mock) -> None:
    """Test 100 concurrent list_paths operations.

    Verifies that async implementation can handle high concurrency
    without thread exhaustion or significant latency degradation.
    """
    num_concurrent = 100
    session_id = "test-session-load"

    async def list_paths_task(_task_id: int) -> dict:
        """Single list_paths task.

        Parameters
        ----------
        _task_id : int
            Task identifier (unused, for task differentiation only).

        Returns
        -------
        dict
            File listing result.
        """
        session_id_var.set(session_id)
        with patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ):
            return await files_adapter.list_paths(
                mock_context,
                path="src",
                max_results=50,
            )

    start_time = time.monotonic()

    # Execute 100 concurrent tasks
    tasks = [list_paths_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    end_time = time.monotonic()
    duration = end_time - start_time

    # Verify all tasks completed successfully
    assert len(results) == num_concurrent
    assert all("items" in result for result in results)
    assert all(isinstance(result["items"], list) for result in results)

    # Verify reasonable performance (should complete in <5 seconds for 100 concurrent)
    assert duration < 5.0, f"100 concurrent requests took {duration:.2f}s (expected <5s)"

    # Calculate average latency per request
    avg_latency_ms = (duration / num_concurrent) * 1000
    print("\nLoad test results:")
    print(f"  Concurrent requests: {num_concurrent}")
    print(f"  Total duration: {duration:.2f}s")
    print(f"  Average latency per request: {avg_latency_ms:.2f}ms")


@pytest.mark.load
@pytest.mark.asyncio
async def test_concurrent_blame_range(mock_context: Mock) -> None:
    """Test 50 concurrent blame_range operations.

    Verifies that async Git operations can handle concurrency
    without blocking the event loop.
    """
    num_concurrent = 50
    session_id = "test-session-load"

    async def blame_task(task_id: int) -> dict:
        """Single blame_range task.

        Parameters
        ----------
        task_id : int
            Task identifier used to select which file to blame.

        Returns
        -------
        dict
            Blame result.
        """
        session_id_var.set(session_id)
        file_num = task_id % 10  # Cycle through first 10 files
        return await history_adapter.blame_range(
            mock_context,
            path=f"src/file_{file_num}.py",
            start_line=1,
            end_line=5,
        )

    start_time = time.monotonic()

    # Execute 50 concurrent tasks
    tasks = [blame_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    end_time = time.monotonic()
    duration = end_time - start_time

    # Verify all tasks completed successfully
    assert len(results) == num_concurrent
    assert all("blame" in result or "error" in result for result in results)

    # Verify reasonable performance
    assert duration < 3.0, f"50 concurrent blame operations took {duration:.2f}s (expected <3s)"

    avg_latency_ms = (duration / num_concurrent) * 1000
    print("\nLoad test results:")
    print(f"  Concurrent blame operations: {num_concurrent}")
    print(f"  Total duration: {duration:.2f}s")
    print(f"  Average latency per request: {avg_latency_ms:.2f}ms")


@pytest.mark.load
@pytest.mark.asyncio
async def test_mixed_concurrent_operations(mock_context: Mock) -> None:
    """Test mixed concurrent operations (list_paths + blame_range).

    Verifies that different async adapters can run concurrently
    without interference.
    """
    num_list_paths = 50
    num_blame = 50
    session_id = "test-session-load"

    async def list_paths_task() -> dict:
        """Single list_paths task.

        Returns
        -------
        dict
            File listing result.
        """
        session_id_var.set(session_id)
        with patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ):
            return await files_adapter.list_paths(mock_context, path="src", max_results=20)

    async def blame_task(task_id: int) -> dict:
        """Single blame_range task.

        Parameters
        ----------
        task_id : int
            Task identifier used to select which file to blame.

        Returns
        -------
        dict
            Blame result.
        """
        session_id_var.set(session_id)
        file_num = task_id % 10
        return await history_adapter.blame_range(
            mock_context,
            path=f"src/file_{file_num}.py",
            start_line=1,
            end_line=3,
        )

    start_time = time.monotonic()

    # Execute mixed concurrent tasks
    list_tasks = [list_paths_task() for _ in range(num_list_paths)]
    blame_tasks = [blame_task(i) for i in range(num_blame)]
    all_tasks = list_tasks + blame_tasks

    results = await asyncio.gather(*all_tasks)

    end_time = time.monotonic()
    duration = end_time - start_time

    # Verify all tasks completed
    assert len(results) == num_list_paths + num_blame

    # Verify reasonable performance
    assert duration < 4.0, f"100 mixed operations took {duration:.2f}s (expected <4s)"

    print("\nMixed load test results:")
    print(f"  list_paths operations: {num_list_paths}")
    print(f"  blame_range operations: {num_blame}")
    print(f"  Total duration: {duration:.2f}s")


@pytest.mark.load
@pytest.mark.asyncio
async def test_no_thread_exhaustion(mock_context: Mock) -> None:
    """Test that high concurrency doesn't cause thread exhaustion.

    This test verifies that async adapters don't exhaust the threadpool
    even under very high concurrency (200+ requests).
    """
    num_concurrent = 200
    session_id = "test-session-load"

    async def list_paths_task(_task_id: int) -> dict:
        """Single list_paths task.

        Parameters
        ----------
        _task_id : int
            Task identifier (unused, for task differentiation only).

        Returns
        -------
        dict
            File listing result.
        """
        session_id_var.set(session_id)
        with patch(
            "codeintel_rev.mcp_server.adapters.files.get_effective_scope",
            return_value=None,
        ):
            return await files_adapter.list_paths(
                mock_context,
                path="src",
                max_results=10,
            )

    start_time = time.monotonic()

    # Execute 200 concurrent tasks
    tasks = [list_paths_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    end_time = time.monotonic()
    duration = end_time - start_time

    # Verify all tasks completed (no thread exhaustion)
    assert len(results) == num_concurrent
    assert all("items" in result for result in results)

    # Should complete without hanging (thread exhaustion would cause hangs)
    assert duration < 10.0, (
        f"200 concurrent requests took {duration:.2f}s (thread exhaustion suspected)"
    )

    print("\nThread exhaustion test:")
    print(f"  Concurrent requests: {num_concurrent}")
    print(f"  Total duration: {duration:.2f}s")
    print("  No thread exhaustion detected")
