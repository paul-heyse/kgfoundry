"""Tests for runtime factory adjustment: noop and default adjusters."""

from __future__ import annotations

from dataclasses import dataclass

from codeintel_rev.runtime.cells import RuntimeCell
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster, NoopFactoryAdjuster

from tests._helpers import assertions


@dataclass(frozen=False)
class _DummyFaiss:
    nprobe: int = 1

    def set_nprobe(self, value: int) -> None:
        self.nprobe = value


def test_noop_adjuster_keeps_factory() -> None:
    """Test that noop adjuster keeps factory unchanged."""
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(NoopFactoryAdjuster())
    inst = cell.get_or_initialize(_DummyFaiss)
    assertions.expect_equal(inst.nprobe, 1)


def test_default_adjuster_updates_nprobe() -> None:
    """Test that default adjuster updates FAISS nprobe parameter."""
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(DefaultFactoryAdjuster(faiss_nprobe=64))
    inst = cell.get_or_initialize(_DummyFaiss)
    assertions.expect_equal(inst.nprobe, 64)


def test_adjuster_runs_once() -> None:
    """Test that factory adjuster runs only once per cell initialization."""
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(DefaultFactoryAdjuster(faiss_nprobe=32))
    calls = {"count": 0}

    def factory() -> _DummyFaiss:
        calls["count"] += 1
        return _DummyFaiss()

    first = cell.get_or_initialize(factory)
    second = cell.get_or_initialize(factory)
    assertions.expect_true(first is second, reason="should be same object")
    assertions.expect_equal(calls["count"], 1)
