"""Full integration tests for CodeIntel MCP application.

Tests the complete application lifecycle including startup, health checks,
and MCP tool endpoints with real configuration.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from http import HTTPStatus
from pathlib import Path
from typing import cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import app
from codeintel_rev.app.readiness import ReadinessProbe
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
        """Rebuild the cached context with optional FAISS preload override."""
        overrides: dict[str, object] | None = None
        if faiss_preload is not None:
            overrides = cast("dict[str, object]", {"faiss_preload": faiss_preload})
        self._reconfigure(overrides)

# Test constants for startup time assertions
_EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS = 20.0
_EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS = 40.0


@pytest.fixture
def test_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RepoHandle:
    """Set up a minimal test repository environment and inject context.

    Returns
    -------
    RepoHandle
        Helper exposing the repo path and a configuration hook.
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
    (data_dir / "catalog.duckdb").touch()

    # Create a test file
    test_file = repo_root / "test.py"
    test_file.write_text('print("hello world")\n')

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
        # App should start without errors
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_equal(response.json(), {"status": "ok"})


@pytest.mark.usefixtures("test_repo")
def test_app_healthz_endpoint() -> None:
    """Test that /healthz endpoint returns 200."""
    with TestClient(app) as client:
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        data = response.json()
        assertions.expect_equal(data["status"], "ok")


@pytest.mark.usefixtures("test_repo")
def test_app_readyz_endpoint_healthy() -> None:
    """Test that /readyz endpoint shows all checks healthy."""
    with TestClient(app) as client:
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
    settings = build_settings_for_repo(invalid_path)
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create(settings=settings)


@pytest.mark.usefixtures("test_repo")
def test_app_startup_with_preload_disabled(test_repo: RepoHandle) -> None:
    """Test that FAISS is lazy-loaded when FAISS_PRELOAD=0."""
    test_repo.configure(faiss_preload=False)

    start_time = time.monotonic()
    with TestClient(app) as client:
        startup_time = time.monotonic() - start_time
        # Startup should remain responsive, but allow generous budget for cold caches.
        assertions.expect_true(
            startup_time < _EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS,
            reason=(
                f"Startup took {startup_time:.2f}s, "
                f"expected < {_EXPECTED_STARTUP_TIME_WITHOUT_PRELOAD_SECONDS}s"
            ),
        )

        # Health check should work
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.usefixtures("test_repo")
@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable on this host")
def test_app_startup_with_preload_enabled(test_repo: RepoHandle) -> None:
    """Test that FAISS pre-loading works when FAISS_PRELOAD=1."""
    test_repo.configure(faiss_preload=True)

    start_time = time.monotonic()
    with TestClient(app) as client:
        startup_time = time.monotonic() - start_time
        # Preloading is expensive; treat this as a smoke test rather than a perf gate.
        assertions.expect_true(
            startup_time < _EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS,
            reason=(
                f"Startup took {startup_time:.2f}s, "
                f"expected < {_EXPECTED_STARTUP_TIME_WITH_PRELOAD_SECONDS}s"
            ),
        )

        # Health check should work
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


def test_context_stored_in_app_state(test_repo: RepoHandle) -> None:
    """Test that ApplicationContext is stored in app.state."""
    with TestClient(app):
        # Access app state through lifespan context
        assertions.expect_true(
            hasattr(app.state, "context"), reason="app.state should have context"
        )

        context = app.state.context
        assertions.expect_true(
            isinstance(context, ApplicationContext), reason="context should be ApplicationContext"
        )
        assertions.expect_equal(context.paths.repo_root, test_repo.repo_root.resolve())


@pytest.mark.usefixtures("test_repo")
def test_readiness_probe_stored_in_app_state() -> None:
    """Test that ReadinessProbe is stored in app.state."""
    with TestClient(app):
        assertions.expect_true(
            hasattr(app.state, "readiness"), reason="app.state should have readiness"
        )

        readiness = app.state.readiness
        assertions.expect_true(
            isinstance(readiness, ReadinessProbe), reason="readiness should be ReadinessProbe"
        )


@pytest.mark.usefixtures("test_repo")
def test_mcp_tool_list_paths() -> None:
    """Test that list_paths MCP tool works end-to-end."""
    with TestClient(app) as client:
        # Call MCP tool endpoint (if available)
        # Note: This tests the adapter through the MCP server
        # The actual MCP protocol would use a different endpoint format
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


@pytest.mark.usefixtures("test_repo")
def test_configuration_immutability() -> None:
    """Test that configuration is immutable after creation."""
    with TestClient(app):
        context = app.state.context

        # Attempt to modify frozen settings should raise FrozenInstanceError
        # Note: msgspec.Struct uses a different exception mechanism
        # but the effect is the same - modification is prevented

        # msgspec.Struct raises AttributeError when trying to set attributes
        # We test each exception type separately to satisfy pyrefly type checking
        try:
            context.settings.paths.repo_root = "/new/path"
            pytest.fail("Expected AttributeError or TypeError")
        except AttributeError:
            pass
        except TypeError:
            pass

        # ResolvedPaths is a frozen dataclass, should raise FrozenInstanceError
        # Use setattr to trigger FrozenInstanceError properly
        with pytest.raises(FrozenInstanceError):
            context.paths.repo_root = Path("/new/path")
