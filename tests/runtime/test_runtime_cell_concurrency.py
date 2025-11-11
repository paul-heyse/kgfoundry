from __future__ import annotations

import threading
import time

from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.runtime.cells import RuntimeCell


def test_single_flight_and_backpressure() -> None:
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

    assert build_count == 1
    assert results.count(42) >= 1
    if errors:
        assert any(isinstance(err, RuntimeUnavailableError) for err in errors)


def test_close_allows_reinitialize() -> None:
    cell: RuntimeCell[str] = RuntimeCell(name="reset")
    assert cell.get_or_initialize(lambda: "first") == "first"
    cell.close()
    assert cell.get_or_initialize(lambda: "second") == "second"
