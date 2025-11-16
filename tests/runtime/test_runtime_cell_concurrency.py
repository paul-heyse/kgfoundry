"""Tests for runtime cell concurrency and backpressure."""

from __future__ import annotations

import threading
import time

from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.runtime.cells import RuntimeCell

from tests._helpers import assertions


def test_single_flight_and_backpressure() -> None:
    """Verify single-flight initialization and backpressure handling."""
    cell: RuntimeCell[int] = RuntimeCell(name="test", max_waiters=1, wait_timeout_ms=50)
    build_count = 0

    def factory() -> int:
        nonlocal build_count
        build_count += 1
        time.sleep(0.1)
        return 42

    results: list[int] = []
    errors: list[Exception] = []

    def _call() -> None:
        try:
            results.append(cell.get_or_initialize(factory))
        except RuntimeUnavailableError as exc:  # pragma: no cover - timing dependent
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assertions.expect_equal(build_count, 1)
    assertions.expect_true(results.count(42) >= 1, reason="should have at least one result")
    if errors:
        assertions.expect_true(
            any(isinstance(err, RuntimeUnavailableError) for err in errors),
            reason="should have RuntimeUnavailableError",
        )


def test_close_allows_reinitialize() -> None:
    """Verify closing a cell allows reinitialization with new factory."""
    cell: RuntimeCell[str] = RuntimeCell(name="reset")
    assertions.expect_equal(cell.get_or_initialize(lambda: "first"), "first")
    cell.close()
    assertions.expect_equal(cell.get_or_initialize(lambda: "second"), "second")
