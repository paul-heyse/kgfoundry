"""Tests for the ScopeRegistry concurrency behaviour."""

from __future__ import annotations

import threading
from typing import Self

import pytest
from codeintel_rev.app.scope_registry import ScopeRegistry


class GaugeProbe:
    """Minimal gauge stub capturing the last set value."""

    def __init__(self) -> None:
        self.value: float | None = None

    def set(self, value: float) -> None:
        self.value = value

    def labels(self, **labels: object) -> GaugeProbe:
        del labels
        return self


class GateableRLock:
    """RLock wrapper that exposes hooks for release coordination."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._release_notifier: threading.Event | None = None
        self._release_gate: threading.Event | None = None

    def configure(self, notifier: threading.Event, gate: threading.Event) -> None:
        self._release_notifier = notifier
        self._release_gate = gate

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
        return self._lock.acquire(blocking=blocking, timeout=timeout)

    def release(self) -> None:
        self._lock.release()
        notifier = self._release_notifier
        gate = self._release_gate
        self._release_notifier = None
        self._release_gate = None
        if notifier is not None:
            notifier.set()
        if gate is not None and not gate.wait(timeout=1.0):
            msg = "release gate was not opened in time"
            raise AssertionError(msg)

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.release()
        return False


@pytest.mark.timeout(5)
def test_gauge_stays_consistent_during_overlapping_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gauge reflects cleared state when set/clear overlap."""
    gauge = GaugeProbe()
    monkeypatch.setattr(
        "codeintel_rev.app.scope_registry._active_sessions_gauge",
        gauge,
    )

    registry = ScopeRegistry()

    gateable_lock = GateableRLock()
    release_notifier = threading.Event()
    release_gate = threading.Event()
    gateable_lock.configure(release_notifier, release_gate)
    registry._lock = gateable_lock  # type: ignore[assignment]

    set_done = threading.Event()
    clear_done = threading.Event()

    def run_set_scope() -> None:
        registry.set_scope("session", {"languages": ["python"]})
        set_done.set()

    def run_clear_scope() -> None:
        registry.clear_scope("session")
        clear_done.set()

    set_thread = threading.Thread(target=run_set_scope)
    set_thread.start()

    assert release_notifier.wait(timeout=1.0), "set_scope did not release the lock"

    clear_thread = threading.Thread(target=run_clear_scope)
    clear_thread.start()
    clear_thread.join(timeout=1.0)
    assert not clear_thread.is_alive(), "clear_scope did not finish"

    release_gate.set()

    set_thread.join(timeout=1.0)
    assert not set_thread.is_alive(), "set_scope did not finish"
    assert set_done.is_set(), "set_scope did not signal completion"
    assert clear_done.is_set(), "clear_scope did not signal completion"

    assert registry.get_session_count() == 0
    assert gauge.value == 0
