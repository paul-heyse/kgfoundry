from __future__ import annotations

from dataclasses import dataclass

from codeintel_rev.runtime.cells import RuntimeCell
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster, NoopFactoryAdjuster


@dataclass(frozen=True)
class _DummyFaiss:
    nprobe: int = 1

    def set_nprobe(self, value: int) -> None:
        object.__setattr__(self, "nprobe", value)


def test_noop_adjuster_keeps_factory() -> None:
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(NoopFactoryAdjuster())
    inst = cell.get_or_initialize(_DummyFaiss)
    assert inst.nprobe == 1


def test_default_adjuster_updates_nprobe() -> None:
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(DefaultFactoryAdjuster(faiss_nprobe=64))
    inst = cell.get_or_initialize(_DummyFaiss)
    assert inst.nprobe == 64


def test_adjuster_runs_once() -> None:
    cell: RuntimeCell[_DummyFaiss] = RuntimeCell(name="coderank-faiss")
    cell.configure_adjuster(DefaultFactoryAdjuster(faiss_nprobe=32))
    calls = {"count": 0}

    def factory() -> _DummyFaiss:
        calls["count"] += 1
        return _DummyFaiss()

    first = cell.get_or_initialize(factory)
    second = cell.get_or_initialize(factory)
    assert first is second
    assert calls["count"] == 1
