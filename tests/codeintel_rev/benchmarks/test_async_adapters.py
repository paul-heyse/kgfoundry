"""Performance benchmarks for async adapters using in-memory harness."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter

from tests._helpers import assertions
from tests._helpers.integration import IntegrationHarness, build_async_adapters_harness

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Benchmarks skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)


@pytest.fixture
def harness(tmp_path: Path) -> IntegrationHarness:
    """Harness configured for async adapter benchmarks.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.

    Returns
    -------
    IntegrationHarness
        Harness with seeded files and async history adapter.
    """
    return build_async_adapters_harness(tmp_path, file_count=200)


def _set_session(session_id: str) -> None:
    session_id_var.set(session_id)


@pytest.mark.benchmark
def test_list_paths_single_request(
    benchmark: BenchmarkFixture,
    harness: IntegrationHarness,
) -> None:
    """Benchmark single list_paths request latency."""
    session_id = "bench-session"

    async def run_async() -> dict:
        _set_session(session_id)
        return await files_adapter.list_paths(harness.context, path="src", max_results=50)

    result = benchmark.pedantic(lambda: asyncio.run(run_async()), rounds=10, iterations=5)

    assertions.expect_in("items", result)
    assertions.expect_true(len(result["items"]) > 0, reason="Adapter should return items.")


@pytest.mark.benchmark
def test_list_paths_concurrent_100(
    benchmark: BenchmarkFixture,
    harness: IntegrationHarness,
) -> None:
    """Benchmark 100 concurrent list_paths requests."""
    num_concurrent = 100
    session_id = "bench-session"

    async def run_concurrent() -> list[dict]:
        async def list_task() -> dict:
            _set_session(session_id)
            return await files_adapter.list_paths(harness.context, path="src", max_results=20)

        tasks = [list_task() for _ in range(num_concurrent)]
        return await asyncio.gather(*tasks)

    results = benchmark.pedantic(lambda: asyncio.run(run_concurrent()), rounds=3, iterations=1)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("items" in result for result in results))
    benchmark.extra_info["concurrent_requests"] = num_concurrent
    benchmark.extra_info["result_count"] = len(results)


@pytest.mark.benchmark
def test_blame_range_single_request(
    benchmark: BenchmarkFixture,
    harness: IntegrationHarness,
) -> None:
    """Benchmark single blame_range request latency."""
    session_id = "bench-session"

    async def run_async() -> dict:
        _set_session(session_id)
        return await history_adapter.blame_range(
            harness.context,
            path="src/file_0.py",
            start_line=1,
            end_line=5,
        )

    result = benchmark.pedantic(lambda: asyncio.run(run_async()), rounds=10, iterations=5)

    assertions.expect_true(
        "blame" in result or "error" in result,
        reason="Adapter should return blame metadata or an error payload.",
    )


@pytest.mark.benchmark
def test_blame_range_concurrent_50(
    benchmark: BenchmarkFixture,
    harness: IntegrationHarness,
) -> None:
    """Benchmark 50 concurrent blame_range requests."""
    num_concurrent = 50
    session_id = "bench-session"

    async def run_concurrent() -> list[dict]:
        async def blame_task(task_id: int) -> dict:
            _set_session(session_id)
            file_num = task_id % 10
            return await history_adapter.blame_range(
                harness.context,
                path=f"src/file_{file_num}.py",
                start_line=1,
                end_line=5,
            )

        tasks = [blame_task(i) for i in range(num_concurrent)]
        return await asyncio.gather(*tasks)

    results = benchmark.pedantic(lambda: asyncio.run(run_concurrent()), rounds=3, iterations=1)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("blame" in result or "error" in result for result in results))
    benchmark.extra_info["git_concurrent_requests"] = num_concurrent
    benchmark.extra_info["git_result_count"] = len(results)


@pytest.mark.benchmark
def test_mixed_concurrent_benchmark(
    benchmark: BenchmarkFixture,
    harness: IntegrationHarness,
) -> None:
    """Benchmark mixed concurrent operations (list_paths + blame_range)."""
    num_list = 50
    num_blame = 50
    session_id = "bench-session"

    async def run_mixed() -> tuple[list[dict], list[dict]]:
        async def list_task() -> dict:
            _set_session(session_id)
            return await files_adapter.list_paths(harness.context, path="src", max_results=20)

        async def blame_task(task_id: int) -> dict:
            _set_session(session_id)
            file_num = task_id % 10
            return await history_adapter.blame_range(
                harness.context,
                path=f"src/file_{file_num}.py",
                start_line=1,
                end_line=3,
            )

        list_tasks = [list_task() for _ in range(num_list)]
        blame_tasks = [blame_task(i) for i in range(num_blame)]
        all_results = await asyncio.gather(*list_tasks, *blame_tasks)

        list_results = all_results[:num_list]
        blame_results = all_results[num_list:]

        return list_results, blame_results

    list_results, blame_results = benchmark.pedantic(
        lambda: asyncio.run(run_mixed()),
        rounds=3,
        iterations=1,
    )

    assertions.expect_equal(len(list_results), num_list)
    assertions.expect_equal(len(blame_results), num_blame)
    benchmark.extra_info["mixed_list_requests"] = num_list
    benchmark.extra_info["mixed_blame_requests"] = num_blame
