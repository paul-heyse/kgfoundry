"""Tests for FastAPI lifespan preload and runtime cleanup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import lifespan
from fastapi import FastAPI

from tests._helpers import assertions
from tests.app._context_factory import build_application_context


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
    """Verify optional runtimes preload and cleanup during lifespan."""
    fake_context = _FakeContext()
    probes: list[_FakeReadinessProbe] = []

    def _fake_create(_cls: type[ApplicationContext]) -> _FakeContext:
        return fake_context

    def _fake_health() -> dict[str, object]:
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
    monkeypatch.setattr("codeintel_rev.app.main.check_faiss_health", _fake_health)
    monkeypatch.setattr("codeintel_rev.app.main.ReadinessProbe", _probe_factory)

    def _flag(name: str) -> bool:
        return name in {"XTR_PRELOAD", "HYBRID_PRELOAD"}

    monkeypatch.setattr("codeintel_rev.app.main._env_flag", _flag)

    app = FastAPI()
    async with lifespan(app):
        pass

    assertions.expect_equal(fake_context.xtr_calls, 1)
    assertions.expect_equal(fake_context.hybrid_calls, 1)
    assertions.expect_equal(fake_context.close_calls, 1)
    assertions.expect_equal(fake_context.scope_store.close_calls, 1)
    assertions.expect_true(bool(probes), reason="should have created probes")
    assertions.expect_equal(probes[0].shutdown_calls, 1)


def test_close_all_runtimes_idempotent(
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure runtime cleanup is idempotent across repeated calls."""

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
    application_context.faiss_manager.cpu_index = cast("Any", object())
    application_context.close_all_runtimes()
    application_context.close_all_runtimes()

    assertions.expect_equal(disposable.closed, 1)
    replacement = application_context.get_hybrid_engine()
    assertions.expect_true(
        replacement is not disposable, reason="should create new instance after close"
    )
    assertions.expect_equal(application_context.faiss_manager.cpu_index, None)


@pytest.fixture(name="_base_application_context")
def _base_application_context_fixture(
    tmp_path: Path,
) -> ApplicationContext:
    """Provide the shared ApplicationContext fixture for this module.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path for creating test repository structure.

    Returns
    -------
    ApplicationContext
        Shared application context instance for test isolation.
    """
    return build_application_context(tmp_path)


@pytest.fixture
def application_context(_base_application_context: ApplicationContext) -> ApplicationContext:
    """Expose the shared application_context fixture to this module.

    Parameters
    ----------
    _base_application_context : ApplicationContext
        The base application context fixture to expose.

    Returns
    -------
    ApplicationContext
        The shared application context instance.
    """
    return _base_application_context
