"""Tests ensuring multiprocessing always uses spawn semantics."""

from __future__ import annotations

import multiprocessing as mp

from codeintel_rev.runtime.multiprocessing import (
    get_spawn_context,
    spawn_process,
    spawn_process_pool,
)

from tests._helpers import assertions


def _queue_worker(queue: mp.Queue) -> None:  # pragma: no cover - executed in subprocess
    """Worker function that puts message in queue.

    Parameters
    ----------
    queue : mp.Queue
        Queue to put message into.
    """
    queue.put("ok")


def _executor_task() -> int:  # pragma: no cover - executed in subprocess
    """Task function that returns computed value.

    Returns
    -------
    int
        Computed value (42).
    """
    return 21 * 2


def test_global_start_method_is_spawn() -> None:
    """Fork start method should never be active on Linux."""
    start_method = mp.get_start_method(allow_none=True)
    assertions.expect_equal(start_method, "spawn")


def test_spawn_context_helpers_use_spawn() -> None:
    """spawn_process and spawn_process_pool wire through the spawn context."""
    queue = get_spawn_context().Queue()

    proc = spawn_process(target=_queue_worker, args=(queue,))
    proc.start()
    proc.join(timeout=5)
    message = queue.get(timeout=1)
    assertions.expect_equal(message, "ok")

    with spawn_process_pool(max_workers=1) as executor:
        result = executor.submit(_executor_task).result(timeout=5)
    expected = 42
    assertions.expect_equal(result, expected)
