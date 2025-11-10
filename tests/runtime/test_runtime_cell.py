"""Tests for :mod:`codeintel_rev.runtime.cells`."""

from __future__ import annotations

import threading
import time

import pytest
from codeintel_rev.runtime import (
    RuntimeCell,
    RuntimeCellCloseResult,
    RuntimeCellInitResult,
    RuntimeCellObserver,
)


class RecordingObserver(RuntimeCellObserver):
    """Thread-safe observer that records cell events for assertions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.init_started: list[str] = []
        self.init_events: list[dict[str, object]] = []
        self.close_events: list[dict[str, object]] = []

    def on_init_start(self, *, cell: str) -> None:
        with self._lock:
            self.init_started.append(cell)

    def on_init_end(self, event: RuntimeCellInitResult) -> None:
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
                }
            )

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:
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


def test_runtime_cell_initializes_once_under_high_concurrency() -> None:
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

    assert len({id(item) for item in results}) == 1
    assert factory_calls == 1
    assert len(observer.init_started) == 1
    assert observer.init_events[-1]["status"] == "ok"


def test_runtime_cell_init_failure_is_reported_and_retriable() -> None:
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
    assert value == 7
    assert calls == ["fail", "success"]
    assert observer.init_events[0]["status"] == "error"
    assert observer.init_events[-1]["status"] == "ok"


def test_runtime_cell_can_reinitialize_after_close() -> None:
    observer = RecordingObserver()
    cell: RuntimeCell[list[int]] = RuntimeCell(observer=observer)
    first = cell.get_or_initialize(list)
    cell.close()
    second = cell.get_or_initialize(list)
    assert first is not second
    assert observer.close_events[-1]["status"] == "ok"


def test_runtime_cell_seed_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")
    cell: RuntimeCell[int] = RuntimeCell()
    cell.seed(1)
    with pytest.raises(RuntimeError):
        cell.seed(2)
    assert cell.get_or_initialize(lambda: 3) == 1
    cell.close()
    assert cell.get_or_initialize(lambda: 5) == 5
    with pytest.raises(RuntimeError):
        cell.seed(4)


def test_runtime_cell_seed_requires_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")
    cell: RuntimeCell[int] = RuntimeCell()
    with pytest.raises(RuntimeError):
        cell.seed(42)


def test_runtime_cell_close_invokes_close_and_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")
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
    assert runtime.closed is True
    close_event = observer.close_events[-1]
    assert close_event["status"] == "ok"
    assert close_event["close_called"] is True


def test_runtime_cell_close_handles_payload_without_close_method() -> None:
    observer = RecordingObserver()

    class NoCloser:
        pass

    cell: RuntimeCell[NoCloser] = RuntimeCell(observer=observer)
    instance = cell.get_or_initialize(NoCloser)
    assert instance is cell.peek()
    cell.close()
    close_event = observer.close_events[-1]
    assert close_event["close_called"] is False
    assert close_event["status"] == "ok"


def test_runtime_cell_close_exception_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")
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
    assert observer.close_events[-1]["status"] == "error"

    cell.seed(ExplodingRuntime())
    with pytest.raises(RuntimeError):
        cell.close(silent=False)


def test_runtime_cell_repr_masks_inner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")

    class SecretRuntime:
        def __repr__(self) -> str:  # pragma: no cover - immaterial to assertion
            return "SECRET_VALUE"

    cell: RuntimeCell[SecretRuntime] = RuntimeCell(name="secret")
    cell.seed(SecretRuntime())
    representation = repr(cell)
    assert "SECRET_VALUE" not in representation
    assert "secret" in representation
