"""Tests for FastAPI lifespan preload and runtime cleanup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import lifespan, override_app_hooks
from codeintel_rev.io.hybrid_search import HybridSearchEngine
from fastapi import FastAPI

from tests._helpers import assertions
from tests.app._context_factory import build_application_context


class _FakeScopeStore:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        """Increment close call counter."""
        self.close_calls += 1


class _FakeContext:
    def __init__(self) -> None:
        index_settings = SimpleNamespace(faiss_preload=False)
        self.app_config = SimpleNamespace(index=index_settings)
        self.settings = SimpleNamespace(index=index_settings)
        self.scope_store = _FakeScopeStore()
        self.close_calls = 0
        self._xtr_calls = 0
        self._hybrid_calls = 0

    def get_xtr_index(self) -> SimpleNamespace:
        """Return fake XTR index and track call count.

        Returns
        -------
        SimpleNamespace
            Fake XTR index with ready=True.
        """
        self._xtr_calls += 1
        return SimpleNamespace(ready=True)

    def get_hybrid_engine(self) -> object:
        """Return fake hybrid engine and track call count.

        Returns
        -------
        object
            Fake hybrid engine instance.
        """
        self._hybrid_calls += 1
        return object()

    def close_all_runtimes(self) -> None:
        """Increment close call counter."""
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
    def __init__(self, context: ApplicationContext | _FakeContext) -> None:
        self.context = context
        self.initialize_calls = 0
        self.shutdown_calls = 0

    async def initialize(self) -> None:
        """Increment initialize call counter."""
        self.initialize_calls += 1

    async def shutdown(self) -> None:
        """Increment shutdown call counter."""
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_lifespan_preload_and_cleanup() -> None:
    """Verify optional runtimes preload and cleanup during lifespan."""
    fake_context = _FakeContext()
    probes: list[_FakeReadinessProbe] = []

    def _probe_factory(context: _FakeContext) -> _FakeReadinessProbe:
        probe = _FakeReadinessProbe(context)
        probes.append(probe)
        return probe

    def _flag(name: str) -> bool:
        return name in {"XTR_PRELOAD", "HYBRID_PRELOAD"}

    with override_app_hooks(
        context_factory=lambda _overrides: fake_context,
        readiness_probe_factory=_probe_factory,
        env_flag_resolver=_flag,
        faiss_health_check=lambda: {"overall_status": "ready"},
    ):
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
) -> None:
    """Ensure runtime cleanup is idempotent across repeated calls."""

    class _Disposable:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            """Increment closed counter."""
            self.closed += 1

    created: list[_Disposable] = []

    def _factory() -> _Disposable:
        instance = _Disposable()
        created.append(instance)
        return instance

    application_context.set_runtime_factories_for_tests(
        hybrid_engine_factory=cast("Callable[[], HybridSearchEngine]", _factory),
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


@pytest.mark.asyncio
async def test_lifespan_closes_resources(tmp_path: Path) -> None:
    """The production lifespan helper should close runtimes and scope stores."""
    base_context = build_application_context(tmp_path)
    tracker = _FakeScopeStore()
    context = base_context.with_overrides(scope_store=tracker)
    readiness = _FakeReadinessProbe(context)

    close_calls = {"count": 0}

    def _track_shutdown(target: ApplicationContext) -> None:
        close_calls["count"] += 1
        target.close_all_runtimes()

    with override_app_hooks(
        context_factory=lambda _overrides: context,
        readiness_probe_factory=lambda _: readiness,
        faiss_health_check=lambda: {"status": "ok"},
        shutdown_observer=_track_shutdown,
    ):
        app = FastAPI(lifespan=lifespan)
        async with app.router.lifespan_context(app):
            pass

    assertions.expect_equal(close_calls["count"], 1)
    assertions.expect_equal(tracker.close_calls, 1)
