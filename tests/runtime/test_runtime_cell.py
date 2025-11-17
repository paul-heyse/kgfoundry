"""Tests for :mod:`codeintel_rev.runtime.cells`."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import cast

import pytest
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.runtime import (
    RuntimeCell,
    RuntimeCellCloseResult,
    RuntimeCellInitContext,
    RuntimeCellInitResult,
    RuntimeCellObserver,
    allow_runtime_cell_seeding,
)

from tests._helpers import assertions


class RecordingObserver(RuntimeCellObserver):
    """Thread-safe observer that records cell events for assertions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.init_started: list[str] = []
        self.init_events: list[dict[str, object]] = []
        self.close_events: list[dict[str, object]] = []

    def on_init_start(
        self,
        *,
        cell: str,
        generation: int,
        context: RuntimeCellInitContext | None = None,
    ) -> None:
        """Record init start event."""
        _ = (generation, context)
        with self._lock:
            self.init_started.append(cell)

    def on_init_end(self, event: RuntimeCellInitResult) -> None:
        """Record init end event."""
        with self._lock:
            self.init_events.append(
                {
                    "cell": event.cell,
                    "status": event.status,
                    "duration_ms": event.duration_ms,
                    "error": event.error,
                    "payload_type": (
                        type(event.payload).__name__ if event.payload is not None else None
                    ),
                    "generation": event.generation,
                }
            )

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:
        """Record close end event."""
        with self._lock:
            self.close_events.append(
                {
                    "cell": event.cell,
                    "status": event.status,
                    "had_payload": event.had_payload,
                    "close_called": event.close_called,
                    "duration_ms": event.duration_ms,
                    "error": event.error,
                }
            )


@pytest.fixture
def runtime_seed_enabled() -> Iterator[None]:
    """Temporarily allow RuntimeCell.seed without touching env vars.

    Yields
    ------
    None
        This fixture yields None. While active, RuntimeCell.seed can be called
        without environment variable toggles.
    """
    with allow_runtime_cell_seeding():
        yield


def test_runtime_cell_initializes_once_under_high_concurrency() -> None:
    """Test that runtime cell initializes only once under high concurrency."""
    observer = RecordingObserver()
    cell: RuntimeCell[dict[str, int]] = RuntimeCell(name="xtr-runtime", observer=observer)
    barrier = threading.Barrier(100)
    factory_calls = 0

    def factory() -> dict[str, int]:
        nonlocal factory_calls
        time.sleep(0.002)
        factory_calls += 1
        return {"value": factory_calls}

    results: list[dict[str, int]] = []

    def worker() -> None:
        barrier.wait()
        results.append(cell.get_or_initialize(factory))

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assertions.expect_equal(len({id(item) for item in results}), 1)
    assertions.expect_equal(factory_calls, 1)
    assertions.expect_equal(len(observer.init_started), 1)
    assertions.expect_equal(observer.init_events[-1]["status"], "ok")
    assertions.expect_equal(observer.init_events[-1]["generation"], 1)


def test_runtime_cell_init_failure_is_reported_and_retriable() -> None:
    """Test that runtime cell reports initialization failures and allows retry."""
    observer = RecordingObserver()
    cell: RuntimeCell[int] = RuntimeCell(observer=observer)
    calls: list[str] = []

    def factory() -> int:
        if not calls:
            calls.append("fail")
            message = "boom"
            raise RuntimeError(message)
        calls.append("success")
        return 7

    with pytest.raises(RuntimeError, match="boom"):
        cell.get_or_initialize(factory)

    value = cell.get_or_initialize(factory)
    assertions.expect_equal(value, 7)
    assertions.expect_equal(calls, ["fail", "success"])
    assertions.expect_equal(observer.init_events[0]["status"], "error")
    assertions.expect_equal(observer.init_events[-1]["status"], "ok")
    assertions.expect_equal(observer.init_events[0]["generation"], 1)
    assertions.expect_equal(observer.init_events[-1]["generation"], 2)


def test_runtime_cell_can_reinitialize_after_close() -> None:
    """Test that runtime cell can reinitialize after being closed."""
    observer = RecordingObserver()
    cell: RuntimeCell[list[int]] = RuntimeCell(observer=observer)
    first = cell.get_or_initialize(list)
    cell.close()
    second = cell.get_or_initialize(list)
    assertions.expect_true(first is not second, reason="should be same object")
    assertions.expect_equal(observer.close_events[-1]["status"], "ok")


def test_runtime_cell_invalidate_triggers_new_generation() -> None:
    """Test that invalidate triggers a new generation of the runtime cell."""
    observer = RecordingObserver()
    cell: RuntimeCell[list[int]] = RuntimeCell(observer=observer)
    first = cell.get_or_initialize(list)
    cell.invalidate()
    second = cell.get_or_initialize(list)
    assertions.expect_true(first is not second, reason="should be same object")
    assertions.expect_equal(observer.init_events[-1]["generation"], 2)


def test_runtime_cell_record_failure_short_circuits_and_recovers() -> None:
    """Test that record_failure short-circuits initialization and recovers after TTL."""
    cell: RuntimeCell[int] = RuntimeCell()
    calls = {"count": 0}

    def factory() -> int:
        calls["count"] += 1
        return 7

    failure = RuntimeUnavailableError("cooldown", runtime="test-runtime")
    cell.record_failure(failure, ttl_seconds=0.05)
    with pytest.raises(RuntimeUnavailableError):
        cell.get_or_initialize(factory)
    assertions.expect_equal(calls["count"], 0)
    time.sleep(0.06)
    result = cell.get_or_initialize(factory)
    assertions.expect_equal(result, 7)
    assertions.expect_equal(calls["count"], 1)


@pytest.mark.usefixtures("runtime_seed_enabled")
def test_runtime_cell_seed_constraints() -> None:
    """Test that runtime cell seed enforces constraints (single seed, requires guard)."""
    cell: RuntimeCell[int] = RuntimeCell()
    cell.seed(1)
    with pytest.raises(RuntimeError):
        cell.seed(2)
    assertions.expect_equal(cell.get_or_initialize(lambda: 3), 1)
    cell.close()
    assertions.expect_equal(cell.get_or_initialize(lambda: 5), 5)
    with pytest.raises(RuntimeError):
        cell.seed(4)


def test_runtime_cell_seed_requires_guard() -> None:
    """Test that runtime cell seed requires explicit guard."""
    cell: RuntimeCell[int] = RuntimeCell()
    with pytest.raises(RuntimeError):
        cell.seed(42)


@pytest.mark.usefixtures("runtime_seed_enabled")
def test_runtime_cell_close_invokes_close_and_observer() -> None:
    """Test that runtime cell close invokes payload close method and observer."""
    observer = RecordingObserver()

    class DummyRuntime:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    runtime = DummyRuntime()
    cell: RuntimeCell[DummyRuntime] = RuntimeCell(name="dummy", observer=observer)
    cell.seed(runtime)
    cell.close()
    assertions.expect_true(runtime.closed, reason="runtime should be closed")
    close_event = observer.close_events[-1]
    assertions.expect_equal(close_event["status"], "ok")
    assertions.expect_true(
        cast("bool", close_event["close_called"]), reason="close_called should be True"
    )


def test_runtime_cell_close_handles_payload_without_close_method() -> None:
    """Test that runtime cell close handles payloads without close method gracefully."""
    observer = RecordingObserver()

    class NoCloser:
        pass

    cell: RuntimeCell[NoCloser] = RuntimeCell(observer=observer)
    instance = cell.get_or_initialize(NoCloser)
    assertions.expect_true(instance is cell.peek(), reason="should be same object")
    cell.close()
    close_event = observer.close_events[-1]
    assertions.expect_false(
        cast("bool", close_event["close_called"]), reason="close_called should be False"
    )
    assertions.expect_equal(close_event["status"], "ok")


@pytest.mark.usefixtures("runtime_seed_enabled")
def test_runtime_cell_close_exception_paths() -> None:
    """Test that runtime cell close handles exceptions in silent and non-silent modes."""
    observer = RecordingObserver()

    class ExplodingRuntime:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1
            message = "boom"
            raise RuntimeError(message)

    cell: RuntimeCell[ExplodingRuntime] = RuntimeCell(observer=observer)
    payload = ExplodingRuntime()
    cell.seed(payload)
    cell.close(silent=True)
    assertions.expect_equal(observer.close_events[-1]["status"], "error")

    cell.seed(ExplodingRuntime())
    with pytest.raises(RuntimeError):
        cell.close(silent=False)


@pytest.mark.usefixtures("runtime_seed_enabled")
def test_runtime_cell_repr_masks_inner() -> None:
    """Test that runtime cell repr masks inner payload representation."""

    class SecretRuntime:
        def __repr__(self) -> str:  # pragma: no cover - immaterial to assertion
            return "SECRET_VALUE"

    cell: RuntimeCell[SecretRuntime] = RuntimeCell(name="secret")
    cell.seed(SecretRuntime())
    representation = repr(cell)
    assertions.expect_false(
        "SECRET_VALUE" in representation, reason="should not expose SECRET_VALUE"
    )
    assertions.expect_in("secret", representation)
