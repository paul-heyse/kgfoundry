"""Unit tests for ReadinessProbe and health checks."""

from __future__ import annotations

import tempfile
from dataclasses import replace as dc_replace
from http import HTTPStatus
from pathlib import Path
from types import TracebackType
from typing import Self
from unittest.mock import Mock

import duckdb
import httpx
import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import readyz
from codeintel_rev.app.runtime_readiness import CheckResult, ReadinessProbe
from codeintel_rev.config.api import AppConfig
from fastapi import FastAPI

from tests._helpers import assertions
from tests._helpers.http import build_test_app


class _FakeHttpClient:
    """Fake HTTP client for testing readiness checks."""

    def __init__(self, *, is_success: bool = True, side_effect: Exception | None = None) -> None:
        """Initialize fake client with success flag and side effect.

        Parameters
        ----------
        is_success : bool, optional
            Whether requests succeed. Defaults to True.
        side_effect : Exception | None, optional
            Exception to raise on get() if set. Defaults to None.
        """
        self._is_success = is_success
        self._side_effect = side_effect

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        _ = exc_type, exc, tb

    def get(self, *_: object, **__: object) -> Mock:
        """Make GET request and return mock response.

        Parameters
        ----------
        *_ : object
            Positional arguments (ignored).
        **__ : object
            Keyword arguments (ignored).

        Returns
        -------
        Mock
            Mock response object.

        Raises
        ------
        Exception
            If side_effect is set.
        """
        if self._side_effect is not None:
            raise self._side_effect
        response = Mock()
        response.is_success = self._is_success
        response.status_code = 200 if self._is_success else 503
        response.text = "error" if not self._is_success else "ok"
        return response


def _materialized_app_config(app_config: AppConfig, *, enabled: bool) -> AppConfig:
    """Return AppConfig copy with duckdb materialization toggle applied.

    Returns
    -------
    AppConfig
        Copy of the input AppConfig with duckdb materialization setting updated.
    """
    return dc_replace(
        app_config,
        index=dc_replace(app_config.index, duckdb_materialize=enabled),
    )


def _reset_duckdb_catalog(db_path: Path) -> None:
    """Replace touch-based DuckDB placeholder with a valid, empty catalog."""
    if db_path.exists():
        db_path.unlink()
    with duckdb.connect(str(db_path)):
        pass


def _context_with_app_config(
    context: ApplicationContext,
    *,
    app_config: AppConfig,
) -> ApplicationContext:
    """Return a context clone with a new AppConfig.

    Returns
    -------
    ApplicationContext
        New application context with the specified AppConfig applied.
    """
    return context.with_overrides(app_config=app_config)


def _http_vllm_app_config(context: ApplicationContext, base_url: str) -> AppConfig:
    """Return AppConfig copy with vLLM HTTP settings.

    Returns
    -------
    AppConfig
        Copy of the active config with HTTP vLLM overrides applied.
    """
    vllm_cfg = dc_replace(context.app_config.vllm, base_url=base_url, run_mode="http")
    return dc_replace(context.app_config, vllm=vllm_cfg)


@pytest.mark.asyncio
async def test_readyz_endpoint_reports_checks(readiness_test_app: FastAPI) -> None:
    """End-to-end /readyz call should report healthy checks via helper app."""
    transport = httpx.ASGITransport(app=readiness_test_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/readyz")
            assertions.expect_equal(response.status_code, HTTPStatus.OK)
            payload = response.json()
            assertions.expect_true(payload["ready"], reason="ready flag should be true")
            assertions.expect_in("checks", payload)
            assertions.expect_in("repo_root", payload["checks"])
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_readyz_endpoint_detects_missing_faiss(readiness_test_app: FastAPI) -> None:
    """/readyz should surface unhealthy status when FAISS index is missing."""
    context: ApplicationContext = readiness_test_app.state.context
    context.paths.faiss_index.unlink(missing_ok=True)
    transport = httpx.ASGITransport(app=readiness_test_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/readyz")
            assertions.expect_equal(response.status_code, HTTPStatus.OK)
            payload = response.json()
            assertions.expect_false(payload["ready"], reason="ready should be false")
            faiss_check = payload["checks"].get("faiss_index", {})
            assertions.expect_false(faiss_check.get("healthy"), reason="FAISS check should fail")
    finally:
        await transport.aclose()


def test_check_result_as_payload_healthy() -> None:
    """Test CheckResult.as_payload() for healthy result."""
    # Arrange
    result = CheckResult(healthy=True)

    # Act
    payload = result.as_payload()

    # Assert
    assertions.expect_equal(payload, {"healthy": True})


def test_check_result_as_payload_unhealthy() -> None:
    """Test CheckResult.as_payload() for unhealthy result with detail."""
    # Arrange
    result = CheckResult(healthy=False, detail="FAISS index not found")

    # Act
    payload = result.as_payload()

    # Assert
    assertions.expect_equal(payload, {"healthy": False, "detail": "FAISS index not found"})


@pytest.mark.asyncio
async def test_readiness_probe_initialize(
    mock_application_context: ApplicationContext,
) -> None:
    """Test ReadinessProbe.initialize() calls refresh."""
    # Arrange
    probe = ReadinessProbe(mock_application_context)

    # Act
    await probe.initialize()

    # Assert
    snapshot = probe.snapshot()
    assertions.expect_true(len(snapshot) > 0, reason="snapshot should have checks")
    assertions.expect_in("repo_root", snapshot)


@pytest.mark.asyncio
async def test_readiness_probe_all_healthy(
    mock_application_context: ApplicationContext,
) -> None:
    """Test ReadinessProbe when all checks pass."""
    # Arrange
    probe = ReadinessProbe(mock_application_context)

    # Act
    results = await probe.refresh()

    # Assert
    assertions.expect_true(results["repo_root"].healthy, reason="repo_root should be healthy")
    assertions.expect_true(results["data_dir"].healthy, reason="data_dir should be healthy")
    assertions.expect_true(results["vectors_dir"].healthy, reason="vectors_dir should be healthy")
    assertions.expect_true(results["faiss_index"].healthy, reason="faiss_index should be healthy")
    assertions.expect_true(
        results["duckdb_catalog"].healthy, reason="duckdb_catalog should be healthy"
    )
    assertions.expect_true(results["scip_index"].healthy, reason="scip_index should be healthy")


@pytest.mark.asyncio
async def test_readiness_probe_materialize_reports_missing_table(
    mock_application_context: ApplicationContext,
) -> None:
    """Readiness should fail when materialization enabled but table missing."""
    _reset_duckdb_catalog(mock_application_context.paths.duckdb_path)
    new_app_config = _materialized_app_config(
        mock_application_context.app_config,
        enabled=True,
    )
    probe = ReadinessProbe(
        _context_with_app_config(
            mock_application_context,
            app_config=new_app_config,
        )
    )

    results = await probe.refresh()
    duckdb_result = results["duckdb_catalog"]

    assertions.expect_false(
        duckdb_result.healthy, reason="duckdb should be unhealthy when table missing"
    )
    assertions.expect_true(duckdb_result.detail is not None, reason="duckdb should have detail")
    if duckdb_result.detail is not None:
        assertions.expect_in("chunks_materialized", duckdb_result.detail)


@pytest.mark.asyncio
async def test_readiness_probe_materialize_validates_index(
    mock_application_context: ApplicationContext,
) -> None:
    """Readiness passes when materialized table and index exist."""
    _reset_duckdb_catalog(mock_application_context.paths.duckdb_path)
    new_app_config = _materialized_app_config(
        mock_application_context.app_config,
        enabled=True,
    )
    context = _context_with_app_config(mock_application_context, app_config=new_app_config)

    with duckdb.connect(str(context.paths.duckdb_path)) as connection:
        connection.execute("DROP VIEW IF EXISTS chunks")
        connection.execute("DROP TABLE IF EXISTS chunks_materialized")
        connection.execute(
            """
            CREATE TABLE chunks_materialized AS
            SELECT
                1::BIGINT AS id,
                'src/example.py'::VARCHAR AS uri,
                0::INTEGER AS start_line,
                10::INTEGER AS end_line,
                0::BIGINT AS start_byte,
                20::BIGINT AS end_byte,
                'example preview'::VARCHAR AS preview,
                [0.1, 0.2]::FLOAT[] AS embedding
            """
        )
        connection.execute("CREATE VIEW chunks AS SELECT * FROM chunks_materialized")
        connection.execute("CREATE INDEX idx_chunks_materialized_uri ON chunks_materialized(uri)")

    probe = ReadinessProbe(context)
    results = await probe.refresh()

    assertions.expect_true(
        results["duckdb_catalog"].healthy, reason="duckdb should be healthy when table exists"
    )


@pytest.mark.asyncio
async def test_readiness_probe_missing_faiss(mock_application_context: ApplicationContext) -> None:
    """Test ReadinessProbe when FAISS index is missing."""
    # Arrange
    mock_application_context.paths.faiss_index.unlink(missing_ok=True)
    probe = ReadinessProbe(mock_application_context)

    # Act
    results = await probe.refresh()

    # Assert
    assertions.expect_false(
        results["faiss_index"].healthy, reason="faiss_index should be unhealthy when missing"
    )
    assertions.expect_true(
        results["faiss_index"].detail is not None, reason="faiss_index should have detail"
    )
    if results["faiss_index"].detail is not None:
        assertions.expect_in("not found", results["faiss_index"].detail.lower())


@pytest.mark.asyncio
async def test_readiness_probe_vllm_unreachable(
    mock_application_context: ApplicationContext,
) -> None:
    """Test ReadinessProbe when vLLM service is unreachable."""
    # Arrange
    context = _context_with_app_config(
        mock_application_context,
        app_config=_http_vllm_app_config(mock_application_context, "http://localhost:8001/v1"),
    )
    probe = ReadinessProbe(
        context,
        http_client_factory=lambda: _FakeHttpClient(
            is_success=False, side_effect=httpx.HTTPError("Connection refused")
        ),
    )

    results = await probe.refresh()

    # Assert
    assertions.expect_false(
        results["vllm_service"].healthy, reason="vllm_service should be unhealthy when unreachable"
    )
    assertions.expect_true(
        results["vllm_service"].detail is not None, reason="vllm_service should have detail"
    )
    if results["vllm_service"].detail is not None:
        assertions.expect_in("unreachable", results["vllm_service"].detail.lower())


@pytest.mark.asyncio
async def test_readiness_probe_caching(mock_application_context: ApplicationContext) -> None:
    """Test that ReadinessProbe caches results."""
    # Arrange
    probe = ReadinessProbe(mock_application_context)
    await probe.initialize()

    # Act - get snapshot without refresh
    snapshot1 = probe.snapshot()

    # Modify context (shouldn't affect cached results)
    mock_application_context.paths.faiss_index.unlink(missing_ok=True)

    snapshot2 = probe.snapshot()

    # Assert - cached results should be identical
    assertions.expect_equal(snapshot1, snapshot2)

    # Refresh should update cache
    await probe.refresh()
    snapshot3 = probe.snapshot()
    assertions.expect_false(
        snapshot3["faiss_index"].healthy, reason="faiss_index should be unhealthy after refresh"
    )


@pytest.mark.asyncio
async def test_readiness_probe_shutdown(mock_application_context: ApplicationContext) -> None:
    """Test ReadinessProbe.shutdown() clears state."""
    # Arrange
    probe = ReadinessProbe(mock_application_context)
    await probe.initialize()

    # Act
    await probe.shutdown()

    # Assert
    with pytest.raises(RuntimeError, match="Readiness probe not initialized"):
        probe.snapshot()


def test_readiness_probe_check_directory_exists() -> None:
    """Test _check_directory() for existing directory."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        # Act
        result = ReadinessProbe.check_directory(path)

        # Assert
        assertions.expect_true(result.healthy, reason="directory check should be healthy")
        assertions.expect_equal(result.detail, None)


def test_readiness_probe_check_directory_create() -> None:
    """Test _check_directory() with create=True."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmpdir:
        new_dir = Path(tmpdir) / "new_subdir"

        # Act
        result = ReadinessProbe.check_directory(new_dir, create=True)

        # Assert
        assertions.expect_true(result.healthy, reason="directory check should be healthy")
        assertions.expect_true(new_dir.exists(), reason="new_dir should exist")
        assertions.expect_true(new_dir.is_dir(), reason="new_dir should be a directory")


def test_readiness_probe_check_file_exists() -> None:
    """Test _check_file() for existing file."""
    # Arrange
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        path = Path(tmpfile.name)

    try:
        # Act
        result = ReadinessProbe.check_file(path, description="test file")

        # Assert
        assertions.expect_true(result.healthy, reason="file check should be healthy")
    finally:
        path.unlink()


def test_readiness_probe_check_file_optional() -> None:
    """Test check_file() with optional=True for missing file."""
    # Arrange
    path = Path("/nonexistent/file.txt")

    # Act
    result = ReadinessProbe.check_file(path, description="test file", optional=True)

    # Assert
    assertions.expect_true(result.healthy, reason="optional files don't fail readiness")
    assertions.expect_true(result.detail is not None, reason="optional file should have detail")
    if result.detail is not None:
        assertions.expect_in("not found", result.detail.lower())


def test_readiness_probe_check_file_required() -> None:
    """Test check_file() with optional=False for missing file."""
    # Arrange
    path = Path("/nonexistent/file.txt")

    # Act
    result = ReadinessProbe.check_file(path, description="test file", optional=False)

    # Assert
    assertions.expect_false(result.healthy, reason="required file should fail when missing")
    assertions.expect_true(result.detail is not None, reason="required file should have detail")
    if result.detail is not None:
        assertions.expect_in("not found", result.detail.lower())


def test_readiness_probe_check_vllm_invalid_url(
    mock_application_context: ApplicationContext,
) -> None:
    """Test _check_vllm_connection() with invalid URL."""
    # Arrange - create new settings with invalid URL
    context = _context_with_app_config(
        mock_application_context,
        app_config=_http_vllm_app_config(mock_application_context, "not-a-valid-url"),
    )
    probe = ReadinessProbe(context)

    # Act
    result = probe.check_vllm_connection()

    # Assert
    assertions.expect_false(result.healthy, reason="vllm should be unhealthy with invalid URL")
    assertions.expect_true(result.detail is not None, reason="vllm should have detail")
    if result.detail is not None:
        assertions.expect_in("invalid", result.detail.lower())


def test_readiness_probe_check_vllm_success(mock_application_context: ApplicationContext) -> None:
    """Test _check_vllm_connection() with successful health check."""
    # Arrange - create new settings with valid URL
    context = _context_with_app_config(
        mock_application_context,
        app_config=_http_vllm_app_config(mock_application_context, "http://localhost:8001/v1"),
    )
    probe = ReadinessProbe(
        context,
        http_client_factory=lambda: _FakeHttpClient(is_success=True),
    )

    result = probe.check_vllm_connection()

    # Assert
    assertions.expect_true(result.healthy, reason="vllm should be healthy when connection succeeds")


def test_readiness_probe_check_vllm_http_error(
    mock_application_context: ApplicationContext,
) -> None:
    """Test _check_vllm_connection() with HTTP error."""
    # Arrange - create new settings with valid URL
    context = _context_with_app_config(
        mock_application_context,
        app_config=_http_vllm_app_config(mock_application_context, "http://localhost:8001/v1"),
    )
    probe = ReadinessProbe(
        context,
        http_client_factory=lambda: _FakeHttpClient(
            is_success=False, side_effect=httpx.HTTPError("Connection refused")
        ),
    )

    result = probe.check_vllm_connection()

    # Assert
    assertions.expect_false(result.healthy, reason="vllm should be unhealthy on HTTP error")
    assertions.expect_true(result.detail is not None, reason="vllm should have detail")
    if result.detail is not None:
        assertions.expect_in("unreachable", result.detail.lower())


@pytest.fixture
def readiness_test_app(mock_application_context: ApplicationContext) -> FastAPI:
    """Provide a FastAPI app exposing the /readyz endpoint via test helpers.

    Returns
    -------
    FastAPI
        Application bound to a helper-built context with `/readyz` registered.
    """
    context = mock_application_context
    readiness = ReadinessProbe(context)
    app = build_test_app(context)
    app.state.context = context
    app.state.readiness = readiness
    app.add_api_route("/readyz", readyz)
    return app
