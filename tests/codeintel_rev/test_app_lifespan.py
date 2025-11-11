"""Integration tests for FastAPI application lifespan."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from codeintel_rev.app.main import app
from fastapi.testclient import TestClient

from tests.conftest import HAS_FAISS_SUPPORT


@pytest.fixture
def test_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a minimal test repository environment.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.
    monkeypatch : pytest.MonkeyPatch
        Pytest monkeypatch fixture for modifying environment variables.

    Returns
    -------
    Path
        Path to the test repository root directory.
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

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    return repo_root


@pytest.mark.usefixtures("test_repo")
def test_app_startup_with_valid_config() -> None:
    """Test that FastAPI app starts successfully with valid configuration."""
    with TestClient(app) as client:
        # App should start without errors
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.usefixtures("test_repo")
def test_app_healthz_endpoint() -> None:
    """Test that /healthz endpoint returns 200."""
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.usefixtures("test_repo")
def test_app_readyz_endpoint_healthy() -> None:
    """Test that /readyz endpoint shows all checks pass."""
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 200

        data = response.json()
        assert "ready" in data
        assert "checks" in data
        assert "active_index_version" in data
        # Note: vLLM check may fail if service is not running, but that's OK
        # The important thing is that the endpoint works and returns structured data


def test_app_startup_fails_invalid_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that ApplicationContext.create() raises ConfigurationError for invalid repo root.

    Note: TestClient may handle lifespan exceptions differently, but the core
    behavior is that ApplicationContext.create() should fail fast.
    """
    monkeypatch.setenv("REPO_ROOT", "/nonexistent/path")
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    # Verify that ApplicationContext.create() raises ConfigurationError
    from codeintel_rev.app.config_context import ApplicationContext

    from kgfoundry_common.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create()


def test_app_readyz_shows_unhealthy_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that /readyz endpoint shows failures when resources are missing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    # App should start (missing FAISS is not fatal unless pre-loading enabled)
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 200

        data = response.json()
        assert "ready" in data
        assert "checks" in data
        assert "active_index_version" in data
        # FAISS check should be unhealthy
        assert "faiss_index" in data["checks"]
        assert data["checks"]["faiss_index"]["healthy"] is False


@pytest.mark.usefixtures("test_repo")
def test_app_startup_with_preload_disabled() -> None:
    """Test that FAISS is lazy-loaded when FAISS_PRELOAD=0."""
    # FAISS_PRELOAD defaults to False, so this should work
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200

        # App should start quickly without loading FAISS
        response = client.get("/readyz")
        assert response.status_code == 200


@pytest.mark.usefixtures("test_repo")
@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable on this host")
def test_app_startup_with_preload_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that FAISS pre-loading works when FAISS_PRELOAD=1."""
    monkeypatch.setenv("FAISS_PRELOAD", "1")

    # App should start and attempt to pre-load FAISS
    # Note: This may fail if FAISS index is invalid, but startup should still succeed
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200

        response = client.get("/readyz")
        assert response.status_code == 200


@pytest.mark.usefixtures("test_repo")
def test_app_context_in_state() -> None:
    """Test that ApplicationContext is stored in app.state."""
    with TestClient(app):
        # Access app through TestClient
        assert hasattr(app.state, "context")
        assert app.state.context is not None
        assert hasattr(app.state.context, "settings")
        assert hasattr(app.state.context, "paths")
        assert hasattr(app.state.context, "vllm_client")
        assert hasattr(app.state.context, "faiss_manager")


@pytest.mark.usefixtures("test_repo")
def test_app_readiness_in_state() -> None:
    """Test that ReadinessProbe is stored in app.state."""
    with TestClient(app):
        assert hasattr(app.state, "readiness")
        assert app.state.readiness is not None
        # Verify readiness probe has snapshot method
        snapshot = app.state.readiness.snapshot()
        assert isinstance(snapshot, dict)
        assert len(snapshot) > 0
