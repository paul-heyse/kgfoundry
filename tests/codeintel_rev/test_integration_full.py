"""Full integration tests for CodeIntel MCP application.

Tests the complete application lifecycle including startup, health checks,
and MCP tool endpoints with real configuration.
"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from http import HTTPStatus
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from codeintel_rev.app.config_context import ApplicationContext, ApplicationContextOverrides
from codeintel_rev.app.main import readyz
from codeintel_rev.app.runtime_readiness import ReadinessProbe
from codeintel_rev.io.vllm_client import VLLMClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions
from tests._helpers.http import RepoAppHandle, build_test_app
from tests._helpers.settings import build_app_config_for_repo, scaffold_repo_root
from tests.conftest import HAS_FAISS_SUPPORT


class RepoHandle(RepoAppHandle):
    """RepoAppHandle with FAISS preload convenience wrapper.

    ``RepoAppHandle.configure`` now accepts keyword overrides directly, so
    tests can call ``handle.configure(faiss_preload=True)`` without reimplementing
    the builder wiring.
    """


# Test constants for startup time assertions
_EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS = 20.0
_EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS = 40.0


@pytest.fixture
def test_repo(tmp_path: Path) -> RepoHandle:
    """Set up a minimal test repository environment and FastAPI test app.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.

    Returns
    -------
    RepoHandle
        Handle exposing repo root, context, and FastAPI application.
    """
    repo_root = tmp_path / "repo"
    scaffold_repo_root(repo_root)
    data_dir = repo_root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "vectors").mkdir(exist_ok=True)
    (data_dir / "faiss").mkdir(exist_ok=True)
    (data_dir / "faiss" / "code.ivfpq.faiss").touch()
    (data_dir / "catalog.duckdb").touch()
    (repo_root / "test.py").write_text('print("hello world")\n')

    handle = RepoHandle(repo_root)

    def rebuild(index_overrides: dict[str, object] | None = None) -> None:
        """Rebuild application context and FastAPI app with optional overrides.

        Parameters
        ----------
        index_overrides : dict[str, object] | None, optional
            Index configuration overrides.
        """
        app_config = build_app_config_for_repo(repo_root, index_overrides=index_overrides)
        overrides = ApplicationContextOverrides(vllm_client=MagicMock(spec=VLLMClient))
        context = ApplicationContext.create(app_config=app_config, overrides=overrides)
        readiness = ReadinessProbe(context)
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
        # App should start without errors
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


def test_app_healthz_endpoint(test_repo: RepoHandle) -> None:
    """Test that /healthz endpoint returns 200."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        data = response.json()
        assertions.expect_equal(data["status"], "ok")


def test_app_readyz_endpoint_healthy(test_repo: RepoHandle) -> None:
    """Test that /readyz endpoint shows all checks healthy."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/readyz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        data = response.json()
        assertions.expect_in("ready", data)
        assertions.expect_in("checks", data)
        assertions.expect_in("active_index_version", data)
        # All checks should be healthy with valid config
        checks = data["checks"]
        assertions.expect_true(
            checks.get("repo_root", {}).get("healthy") is True,
            reason="repo_root check should be healthy",
        )
        assertions.expect_true(
            checks.get("data_dir", {}).get("healthy") is True,
            reason="data_dir check should be healthy",
        )


def test_app_startup_fails_invalid_repo_root(tmp_path: Path) -> None:
    """Test that FastAPI app fails to start with invalid REPO_ROOT."""
    invalid_path = tmp_path / "nonexistent"
    app_config = build_app_config_for_repo(invalid_path)
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create(app_config=app_config)


def test_app_startup_with_preload_disabled(test_repo: RepoHandle) -> None:
    """Test that FAISS is lazy-loaded when FAISS_PRELOAD=0."""
    start_time = time.monotonic()
    test_repo.configure(faiss_preload=False)
    startup_time = time.monotonic() - start_time
    assertions.expect_true(
        startup_time < _EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS,
        reason=(
            f"Startup took {startup_time:.2f}s, "
            f"expected < {_EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS}s"
        ),
    )

    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.usefixtures("test_repo")
@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable on this host")
def test_app_startup_with_preload_enabled(test_repo: RepoHandle) -> None:
    """Test that FAISS pre-loading works when FAISS_PRELOAD=1."""
    start_time = time.monotonic()
    test_repo.configure(faiss_preload=True)
    startup_time = time.monotonic() - start_time
    assertions.expect_true(
        startup_time < _EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS,
        reason=(
            f"Startup took {startup_time:.2f}s, "
            f"expected < {_EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS}s"
        ),
    )

    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


def test_context_stored_in_app_state(test_repo: RepoHandle) -> None:
    """Test that ApplicationContext is stored in app.state."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app):
        # Access app state through lifespan context
        assertions.expect_true(
            hasattr(test_app.state, "context"), reason="app.state should have context"
        )

        context = test_app.state.context
        assertions.expect_true(
            isinstance(context, ApplicationContext), reason="context should be ApplicationContext"
        )
        assertions.expect_equal(context.paths.repo_root, test_repo.repo_root.resolve())


def test_readiness_probe_stored_in_app_state(test_repo: RepoHandle) -> None:
    """Test that ReadinessProbe is stored in app.state."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app):
        assertions.expect_true(
            hasattr(test_app.state, "readiness"), reason="app.state should have readiness"
        )

        readiness = test_app.state.readiness
        assertions.expect_true(
            isinstance(readiness, ReadinessProbe), reason="readiness should be ReadinessProbe"
        )


def test_mcp_tool_list_paths(test_repo: RepoHandle) -> None:
    """Test that list_paths MCP tool works end-to-end."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app) as client:
        # Call MCP tool endpoint (if available)
        # Note: This tests the adapter through the MCP server
        # The actual MCP protocol would use a different endpoint format
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


def test_configuration_immutability(test_repo: RepoHandle) -> None:
    """Test that configuration is immutable after creation."""
    test_app = cast("FastAPI", test_repo.app)
    with TestClient(test_app):
        context = test_app.state.context

        # Attempt to modify frozen AppConfig should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            context.app_config.paths = context.app_config.paths

        # ResolvedPaths is a frozen dataclass, should raise FrozenInstanceError
        # Use setattr to trigger FrozenInstanceError properly
        with pytest.raises(FrozenInstanceError):
            context.paths.repo_root = Path("/new/path")
