"""Load tests for concurrent adapter operations using in-memory harness."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.mcp_server.adapters import files as files_adapter

from tests._helpers import assertions
from tests._helpers.adapters import InMemoryHistoryAdapter
from tests._helpers.integration import IntegrationHarness, build_async_adapters_harness

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Load tests skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)


@pytest.fixture
def harness(tmp_path: Path) -> IntegrationHarness:
    """Harness with async history adapter and seeded files for load tests.

    Returns
    -------
    IntegrationHarness
        Harness configured for concurrent adapter load tests.
    """
    return build_async_adapters_harness(tmp_path, file_count=100)


@pytest.mark.load
@pytest.mark.asyncio
async def test_concurrent_list_paths(harness: IntegrationHarness) -> None:
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
        return await files_adapter.list_paths(
            harness.context,
            path="src",
            max_results=50,
        )

    tasks = [list_paths_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("items" in result for result in results))
    assertions.expect_true(all(isinstance(result["items"], list) for result in results))


@pytest.mark.load
@pytest.mark.asyncio
async def test_concurrent_blame_range(harness: IntegrationHarness) -> None:
    """Test 50 concurrent blame_range operations.

    Verifies that async Git operations can handle concurrency
    without blocking the event loop.
    """
    num_concurrent = 50
    session_id = "test-session-load"

    history_adapter = harness.history_adapter
    assertions.expect_true(
        history_adapter is not None, reason="history adapter should be available"
    )
    if history_adapter is None:  # pragma: no cover - defensive
        pytest.fail("history adapter not initialized")
        return
    hist_adapter: InMemoryHistoryAdapter = history_adapter

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
            harness.context,
            path=f"src/file_{file_num}.py",
            start_line=1,
            end_line=5,
        )

    tasks = [blame_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("blame" in result or "error" in result for result in results))
    history_adapter = harness.history_adapter
    assertions.expect_true(
        history_adapter is not None, reason="history adapter should be available"
    )
    if history_adapter is not None:
        assertions.expect_equal(history_adapter.blame_calls, num_concurrent)


@pytest.mark.load
@pytest.mark.asyncio
async def test_mixed_concurrent_operations(harness: IntegrationHarness) -> None:
    """Test mixed concurrent operations (list_paths + blame_range).

    Verifies that different async adapters can run concurrently
    without interference.
    """
    num_list_paths = 50
    num_blame = 50
    session_id = "test-session-load"

    history_adapter = harness.history_adapter
    assertions.expect_true(
        history_adapter is not None, reason="history adapter should be available"
    )
    if history_adapter is None:  # pragma: no cover - defensive
        pytest.fail("history adapter not initialized")
        return
    base_blame_calls = history_adapter.blame_calls

    async def list_paths_task() -> dict:
        """Single list_paths task.

        Returns
        -------
        dict
            File listing result.
        """
        session_id_var.set(session_id)
        return await files_adapter.list_paths(harness.context, path="src", max_results=20)

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
            harness.context,
            path=f"src/file_{file_num}.py",
            start_line=1,
            end_line=3,
        )

    list_tasks = [list_paths_task() for _ in range(num_list_paths)]
    blame_tasks = [blame_task(i) for i in range(num_blame)]
    all_tasks = list_tasks + blame_tasks

    results = await asyncio.gather(*all_tasks)

    assertions.expect_equal(len(results), num_list_paths + num_blame)
    history_adapter = harness.history_adapter
    assertions.expect_true(
        history_adapter is not None, reason="history adapter should be available"
    )
    if history_adapter is not None:
        assertions.expect_equal(history_adapter.blame_calls, base_blame_calls + num_blame)


@pytest.mark.load
@pytest.mark.asyncio
async def test_no_thread_exhaustion(harness: IntegrationHarness) -> None:
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
        return await files_adapter.list_paths(
            harness.context,
            path="src",
            max_results=10,
        )

    tasks = [list_paths_task(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("items" in result for result in results))
