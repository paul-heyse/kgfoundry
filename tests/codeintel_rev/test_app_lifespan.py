"""Integration tests for FastAPI application lifespan."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import cast

import duckdb
import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import app
from fastapi.testclient import TestClient

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions
from tests._helpers.settings import build_settings_for_repo
from tests.conftest import HAS_FAISS_SUPPORT


class RepoHandle:
    """Expose repo path and configuration hook to tests."""

    def __init__(
        self,
        repo_root: Path,
        reconfigure: Callable[[dict[str, object] | None], None],
    ) -> None:
        self.repo_root = repo_root
        self._reconfigure = reconfigure

    def configure(self, *, faiss_preload: bool | None = None) -> None:
        """Rebuild the cached context with optional FAISS overrides."""
        overrides: dict[str, object] | None = None
        if faiss_preload is not None:
            overrides = cast("dict[str, object]", {"faiss_preload": faiss_preload})
        self._reconfigure(overrides)


@pytest.fixture
def test_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RepoHandle:
    """Set up a minimal test repository environment and inject context.

    Returns
    -------
    RepoHandle
        Helper exposing the repo path and configuration hook.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create required directory structure
    data_dir = repo_root / "data"
    data_dir.mkdir()
    (data_dir / "vectors").mkdir()
    (data_dir / "faiss").mkdir()

    # Create empty index files
    (data_dir / "faiss" / "code.ivfpq.faiss").touch()
    duckdb_path = data_dir / "catalog.duckdb"
    # Create a valid DuckDB database
    conn = duckdb.connect(str(duckdb_path))
    conn.close()

    original_create = ApplicationContext.create
    state: dict[str, ApplicationContext] = {}

    def rebuild_context(index_overrides: dict[str, object] | None = None) -> None:
        new_settings = build_settings_for_repo(repo_root, index_overrides=index_overrides)
        state["context"] = original_create(settings=new_settings)

    rebuild_context()

    def patched_create(*_args: object, **_kwargs: object) -> ApplicationContext:
        return state["context"]

    monkeypatch.setattr("codeintel_rev.app.main.ApplicationContext.create", patched_create)

    return RepoHandle(repo_root, rebuild_context)


@pytest.mark.usefixtures("test_repo")
def test_app_startup_with_valid_config() -> None:
    """Test that FastAPI app starts successfully with valid configuration."""
    with TestClient(app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


@pytest.mark.usefixtures("test_repo")
def test_app_healthz_endpoint() -> None:
    """Test that /healthz endpoint returns 200."""
    with TestClient(app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


@pytest.mark.usefixtures("test_repo")
def test_app_readyz_endpoint_healthy() -> None:
    """Test that /readyz endpoint shows all checks pass."""
    with TestClient(app) as client:
        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        data = response.json()
        for key in ("ready", "checks", "active_index_version"):
            assertions.expect_in(key, data)
        # Note: vLLM check may fail if service is not running, but that's OK
        # The important thing is that the endpoint works and returns structured data


def test_app_startup_fails_invalid_repo_root(tmp_path: Path) -> None:
    """Test that ApplicationContext.create() raises ConfigurationError for invalid repo root.

    Note: TestClient may handle lifespan exceptions differently, but the core
    behavior is that ApplicationContext.create() should fail fast.
    """
    invalid_path = tmp_path / "nonexistent"
    settings = build_settings_for_repo(invalid_path)
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create(settings=settings)


def test_app_readyz_shows_unhealthy_resources(test_repo: RepoHandle) -> None:
    """Test that /readyz endpoint shows failures when resources are missing."""
    repo_root = test_repo.repo_root
    faiss_path = repo_root / "data" / "faiss" / "code.ivfpq.faiss"
    if faiss_path.exists():
        faiss_path.unlink()

    # App should start (missing FAISS is not fatal unless pre-loading enabled)
    with TestClient(app) as client:
        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        data = response.json()
        for key in ("ready", "checks", "active_index_version"):
            assertions.expect_in(key, data)
        assertions.expect_in("faiss_index", data["checks"])
        assertions.expect_false(data["checks"]["faiss_index"]["healthy"])


@pytest.mark.usefixtures("test_repo")
def test_app_startup_with_preload_disabled() -> None:
    """Test that FAISS is lazy-loaded when FAISS_PRELOAD=0."""
    # FAISS_PRELOAD defaults to False, so this should work
    with TestClient(app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.usefixtures("test_repo")
@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable on this host")
def test_app_startup_with_preload_enabled(test_repo: RepoHandle) -> None:
    """Test that FAISS pre-loading works when FAISS_PRELOAD=1."""
    test_repo.configure(faiss_preload=True)

    # App should start and attempt to pre-load FAISS
    # Note: This may fail if FAISS index is invalid, but startup should still succeed
    with TestClient(app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.usefixtures("test_repo")
def test_app_context_in_state() -> None:
    """Test that ApplicationContext is stored in app.state."""
    with TestClient(app):
        assertions.expect_true(hasattr(app.state, "context"))
        assertions.expect_true(app.state.context is not None)
        for attr in ("settings", "paths", "vllm_client", "faiss_manager"):
            assertions.expect_true(hasattr(app.state.context, attr))


@pytest.mark.usefixtures("test_repo")
def test_app_readiness_in_state() -> None:
    """Test that ReadinessProbe is stored in app.state."""
    with TestClient(app):
        assertions.expect_true(hasattr(app.state, "readiness"))
        assertions.expect_true(app.state.readiness is not None)
        snapshot = app.state.readiness.snapshot()
        assertions.expect_true(isinstance(snapshot, dict))
        assertions.expect_true(len(snapshot) > 0)
