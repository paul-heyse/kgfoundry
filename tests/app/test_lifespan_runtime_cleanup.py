"""Tests for FastAPI lifespan preload and runtime cleanup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import lifespan
from fastapi import FastAPI


class _FakeScopeStore:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FakeContext:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            index=SimpleNamespace(faiss_preload=False),
        )
        self.scope_store = _FakeScopeStore()
        self.close_calls = 0
        self._xtr_calls = 0
        self._hybrid_calls = 0

    def get_xtr_index(self) -> SimpleNamespace:
        self._xtr_calls += 1
        return SimpleNamespace(ready=True)

    def get_hybrid_engine(self) -> object:
        self._hybrid_calls += 1
        return object()

    def close_all_runtimes(self) -> None:
        self.close_calls += 1

    @property
    def xtr_calls(self) -> int:
        """Return the number of XTR preload attempts."""
        return self._xtr_calls

    @property
    def hybrid_calls(self) -> int:
        """Return the number of hybrid preload attempts."""
        return self._hybrid_calls


class _FakeReadinessProbe:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.initialize_calls = 0
        self.shutdown_calls = 0

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_lifespan_preload_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_context = _FakeContext()
    probes: list[_FakeReadinessProbe] = []

    def _fake_create(_cls: type[ApplicationContext]) -> _FakeContext:
        return fake_context

    def _fake_warmup() -> dict[str, object]:
        return {"overall_status": "ready", "details": {}}

    def _probe_factory(context: _FakeContext) -> _FakeReadinessProbe:
        probe = _FakeReadinessProbe(context)
        probes.append(probe)
        return probe

    monkeypatch.setattr(
        ApplicationContext,
        "create",
        classmethod(_fake_create),
    )
    monkeypatch.setattr("codeintel_rev.app.main.warmup_gpu", _fake_warmup)
    monkeypatch.setattr("codeintel_rev.app.main.ReadinessProbe", _probe_factory)
    monkeypatch.setenv("XTR_PRELOAD", "1")
    monkeypatch.setenv("HYBRID_PRELOAD", "1")

    app = FastAPI()
    async with lifespan(app):
        pass

    assert fake_context.xtr_calls == 1
    assert fake_context.hybrid_calls == 1
    assert fake_context.close_calls == 1
    assert fake_context.scope_store.close_calls == 1
    assert probes
    assert probes[0].shutdown_calls == 1


def test_close_all_runtimes_idempotent(
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Disposable:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    created: list[_Disposable] = []

    def _factory(*_: object, **__: object) -> _Disposable:
        instance = _Disposable()
        created.append(instance)
        return instance

    monkeypatch.setattr(
        "codeintel_rev.app.config_context.HybridSearchEngine",
        _factory,
    )
    application_context.get_hybrid_engine()
    disposable = created[0]
    application_context.faiss_manager.gpu_index = cast("Any", object())
    application_context.faiss_manager.secondary_gpu_index = cast("Any", object())
    application_context.faiss_manager.cpu_index = cast("Any", object())
    application_context.close_all_runtimes()
    application_context.close_all_runtimes()

    assert disposable.closed == 1
    replacement = application_context.get_hybrid_engine()
    assert replacement is not disposable
    assert application_context.faiss_manager.gpu_index is None
    assert application_context.faiss_manager.secondary_gpu_index is None
    assert application_context.faiss_manager.cpu_index is None


@pytest.fixture
def application_context(_base_application_context):
    """Expose the shared application_context fixture to this module."""
    return _base_application_context
