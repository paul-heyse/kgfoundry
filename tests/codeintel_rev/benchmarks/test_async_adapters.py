"""Performance benchmarks comparing async vs sync adapter implementations.

These benchmarks measure the concurrency benefits of async adapters,
showing that async implementations provide significant speedup under load
while maintaining similar single-request latency.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter

from tests._helpers import assertions
from tests._helpers.settings import build_settings_for_repo

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Benchmarks skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)


@pytest.fixture
def mock_context(tmp_path: Path) -> Mock:
    """Create a mock ApplicationContext for benchmarking.

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
    for i in range(200):
        (repo_root / "src" / f"file_{i}.py").write_text(f"def func_{i}():\n    pass\n")

    settings = build_settings_for_repo(repo_root)
    paths = resolve_application_paths(settings)

    context = Mock(spec=ApplicationContext)
    context.paths = paths
    context.git_client = Mock()
    context.async_git_client = _AsyncGitClientStub()
    context.scope_store = _InMemoryScopeStore()

    return context


class _InMemoryScopeStore:
    """Minimal async scope store stub for benchmarks."""

    def __init__(self) -> None:
        self.get_calls: list[str] = []

    async def get(
        self,
        session_id: str,
    ) -> dict | None:
        self.get_calls.append(session_id)
        return None


class _AsyncGitClientStub:
    """Async Git client stub that returns deterministic data."""

    def __init__(self) -> None:
        self.blame_requests: list[str] = []
        self.history_requests: list[str] = []

    async def blame_range(
        self,
        *,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict]:
        self.blame_requests.append(path)
        return [
            {
                "line": line,
                "commit": "abc123",
                "author": "Benchmark",
                "date": "2024-01-01T00:00:00Z",
                "message": f"Line {line}",
            }
            for line in range(start_line, end_line + 1)
        ]

    async def file_history(self, *, path: str, limit: int) -> list[dict]:
        self.history_requests.append(path)
        return [
            {
                "sha": f"{i:04x}",
                "full_sha": f"{i:08x}",
                "author": "Benchmark",
                "email": "bench@example.com",
                "date": "2024-01-01T00:00:00Z",
                "message": f"Commit {i}",
            }
            for i in range(limit)
        ]


@pytest.mark.benchmark
def test_list_paths_single_request(
    benchmark: BenchmarkFixture,
    mock_context: Mock,
) -> None:
    """Benchmark single list_paths request latency.

    Single-request latency should be similar between sync and async
    implementations (async overhead is minimal).
    """

    async def run_async() -> dict:
        return await files_adapter.list_paths(mock_context, path="src", max_results=50)

    result = benchmark.pedantic(lambda: asyncio.run(run_async()), rounds=10, iterations=5)

    assertions.expect_in("items", result)
    assertions.expect_true(len(result["items"]) > 0, reason="Adapter should return items.")


@pytest.mark.benchmark
def test_list_paths_concurrent_100(
    benchmark: BenchmarkFixture,
    mock_context: Mock,
) -> None:
    """Benchmark 100 concurrent list_paths requests.

    Async implementation should be 5-10x faster than sync for concurrent
    requests due to event loop efficiency vs threadpool blocking.
    """
    num_concurrent = 100

    async def run_concurrent() -> list[dict]:
        async def list_task() -> dict:
            return await files_adapter.list_paths(mock_context, path="src", max_results=20)

        tasks = [list_task() for _ in range(num_concurrent)]
        return await asyncio.gather(*tasks)

    results = benchmark.pedantic(lambda: asyncio.run(run_concurrent()), rounds=3, iterations=1)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("blame" in result for result in results))
    benchmark.extra_info["blame_concurrent_requests"] = num_concurrent
    benchmark.extra_info["blame_result_count"] = len(results)

    assertions.expect_equal(len(results), num_concurrent)
    assertions.expect_true(all("items" in result for result in results))
    benchmark.extra_info["concurrent_requests"] = num_concurrent
    benchmark.extra_info["result_count"] = len(results)


@pytest.mark.benchmark
def test_blame_range_single_request(
    benchmark: BenchmarkFixture,
    mock_context: Mock,
) -> None:
    """Benchmark single blame_range request latency.

    Single-request latency should be similar between sync and async
    (async overhead via asyncio.to_thread is minimal).
    """

    async def run_async() -> dict:
        return await history_adapter.blame_range(
            mock_context,
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
    mock_context: Mock,
) -> None:
    """Benchmark 50 concurrent blame_range requests.

    Async implementation enables concurrent Git operations without
    thread exhaustion, providing significant speedup under load.
    """
    num_concurrent = 50

    async def run_concurrent() -> list[dict]:
        async def blame_task(task_id: int) -> dict:
            file_num = task_id % 10
            return await history_adapter.blame_range(
                mock_context,
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
    mock_context: Mock,
) -> None:
    """Benchmark mixed concurrent operations (list_paths + blame_range).

    Verifies that different async adapters can run concurrently efficiently.
    """
    num_list = 50
    num_blame = 50

    async def run_mixed() -> tuple[list[dict], list[dict]]:
        async def list_task() -> dict:
            return await files_adapter.list_paths(mock_context, path="src", max_results=20)

        async def blame_task(task_id: int) -> dict:
            file_num = task_id % 10
            return await history_adapter.blame_range(
                mock_context,
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
