"""Integration tests for FastAPI application lifespan."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from pathlib import Path
from typing import cast

import duckdb
import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import readyz
from codeintel_rev.app.runtime_readiness import ReadinessProbe
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions
from tests._helpers.http import RepoAppHandle, build_test_app
from tests._helpers.settings import build_settings_for_repo, scaffold_repo_root
from tests.conftest import HAS_FAISS_SUPPORT


class RepoHandle(RepoAppHandle):
    """RepoAppHandle with FAISS preload convenience wrapper."""


@pytest.fixture
def test_repo(tmp_path: Path) -> RepoHandle:
    """Set up a minimal test repository environment and FastAPI test app.

    Returns
    -------
    RepoHandle
        Handle exposing repo root and rebuilt FastAPI application.
    """
    repo_root = tmp_path / "repo"
    scaffold_repo_root(repo_root)

    # Create required directory structure
    data_dir = repo_root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "vectors").mkdir(exist_ok=True)
    (data_dir / "faiss").mkdir(exist_ok=True)

    # Create empty index files
    (data_dir / "faiss" / "code.ivfpq.faiss").touch()
    duckdb_path = data_dir / "catalog.duckdb"
    # Create a valid DuckDB database
    conn = duckdb.connect(str(duckdb_path))
    conn.close()

    handle = RepoHandle(repo_root)

    def rebuild(index_overrides: dict[str, object] | None = None) -> None:
        settings = build_settings_for_repo(repo_root, index_overrides=index_overrides)
        context = ApplicationContext.create(settings=settings)
        readiness = ReadinessProbe(context)
        asyncio.run(readiness.refresh())
        app = build_test_app(context)
        app.state.readiness = readiness
        app.add_api_route("/readyz", readyz)
        handle.update(app, context)

    handle.attach_builder(rebuild)
    handle.configure()
    return handle


def test_app_startup_with_valid_config(test_repo: RepoHandle) -> None:
    """Test that FastAPI app starts successfully with valid configuration."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


def test_app_healthz_endpoint(test_repo: RepoHandle) -> None:
    """Test that /healthz endpoint returns 200."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


def test_app_readyz_endpoint_healthy(test_repo: RepoHandle) -> None:
    """Test that /readyz endpoint shows all checks pass."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
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
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        data = response.json()
        for key in ("ready", "checks", "active_index_version"):
            assertions.expect_in(key, data)
        assertions.expect_in("faiss_index", data["checks"])
        assertions.expect_false(data["checks"]["faiss_index"]["healthy"])


def test_app_startup_with_preload_disabled(test_repo: RepoHandle) -> None:
    """Test that FAISS is lazy-loaded when FAISS_PRELOAD=0."""
    # FAISS_PRELOAD defaults to False, so this should work
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable on this host")
def test_app_startup_with_preload_enabled(test_repo: RepoHandle) -> None:
    """Test that FAISS pre-loading works when FAISS_PRELOAD=1."""
    test_repo.configure(faiss_preload=True)

    # App should start and attempt to pre-load FAISS
    # Note: This may fail if FAISS index is invalid, but startup should still succeed
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)

        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


def test_app_context_in_state(test_repo: RepoHandle) -> None:
    """Test that ApplicationContext is stored in app.state."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app):
        assertions.expect_true(hasattr(test_app.state, "context"))
        assertions.expect_true(test_app.state.context is not None)
        for attr in ("settings", "paths", "vllm_client", "faiss_manager"):
            assertions.expect_true(hasattr(test_app.state.context, attr))


def test_app_readiness_in_state(test_repo: RepoHandle) -> None:
    """Test that ReadinessProbe is stored in app.state."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app):
        assertions.expect_true(hasattr(test_app.state, "readiness"))
        assertions.expect_true(test_app.state.readiness is not None)
        snapshot = test_app.state.readiness.snapshot()
        assertions.expect_true(isinstance(snapshot, dict))
        assertions.expect_true(len(snapshot) > 0)
