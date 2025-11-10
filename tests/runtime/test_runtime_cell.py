"""Tests for :mod:`codeintel_rev.runtime.cells`."""

from __future__ import annotations

import threading
import time

import pytest
from codeintel_rev.runtime import RuntimeCell


def test_runtime_cell_initializes_once_under_race() -> None:
    cell: RuntimeCell[dict[str, int]] = RuntimeCell(name="xtr-runtime")
    barrier = threading.Barrier(8)
    factory_calls = 0

    def factory() -> dict[str, int]:
        nonlocal factory_calls
        time.sleep(0.01)
        factory_calls += 1
        return {"value": factory_calls}

    results: list[dict[str, int]] = []

    def worker() -> None:
        barrier.wait()
        results.append(cell.get_or_initialize(factory))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(item) for item in results}) == 1
    assert factory_calls == 1


def test_runtime_cell_seed_requires_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")
    monkeypatch.delenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", raising=False)
    cell: RuntimeCell[int] = RuntimeCell()
    with pytest.raises(RuntimeError):
        cell.seed(42)


def test_runtime_cell_seed_succeeds_with_env_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")
    cell: RuntimeCell[int] = RuntimeCell()
    cell.seed(123)
    assert cell.get_or_initialize(lambda: 0) == 123


def test_runtime_cell_close_invokes_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")

    class DummyRuntime:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    runtime = DummyRuntime()
    cell: RuntimeCell[DummyRuntime] = RuntimeCell(name="dummy")
    cell.seed(runtime)
    cell.close()
    assert runtime.closed is True
    assert cell.peek() is None


def test_runtime_cell_close_raises_when_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")

    class ExplodingRuntime:
        def close(self) -> None:
            message = "boom"
            raise RuntimeError(message)

    cell: RuntimeCell[ExplodingRuntime] = RuntimeCell()
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


def test_runtime_cell_can_reinitialize_after_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGFOUNDRY_ALLOW_RUNTIME_SEED", "1")
    cell: RuntimeCell[list[int]] = RuntimeCell()
    first = []
    cell.seed(first)
    cell.close()
    second = cell.get_or_initialize(list)
    assert second == []
    assert second is not first
