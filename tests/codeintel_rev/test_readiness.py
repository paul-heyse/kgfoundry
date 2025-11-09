"""Unit tests for ReadinessProbe and health checks."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import duckdb
import httpx
import pytest
from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
from codeintel_rev.app.readiness import CheckResult, ReadinessProbe
from codeintel_rev.config.settings import (
    IndexConfig,
    Settings,
    VLLMConfig,
    load_settings,
)


@pytest.fixture
def mock_context(tmp_path: Path) -> ApplicationContext:
    """Create a mock ApplicationContext for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    ApplicationContext
        Mock application context with test paths and settings.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "vectors").mkdir()
    (repo_root / "data" / "faiss").mkdir()
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").touch()
    (repo_root / "data" / "coderank_vectors").mkdir()
    (repo_root / "data" / "faiss" / "coderank.faiss").touch()
    (repo_root / "indexes").mkdir()
    (repo_root / "indexes" / "warp_xtr").mkdir()
    (repo_root / "index.scip").touch()

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
        coderank_vectors_dir=repo_root / "data" / "coderank_vectors",
        coderank_faiss_index=repo_root / "data" / "faiss" / "coderank.faiss",
        warp_index_dir=repo_root / "indexes" / "warp_xtr",
    )

    settings = load_settings()
    context = Mock(spec=ApplicationContext)
    context.paths = paths
    context.settings = settings

    return context


def _materialized_index_config(index: IndexConfig, *, enabled: bool) -> IndexConfig:
    """Return a copy of IndexConfig with duckdb_materialize toggled.

    Parameters
    ----------
    index : IndexConfig
        Baseline index configuration to copy.
    enabled : bool
        Flag indicating whether duckdb materialization should be enabled.

    Returns
    -------
    IndexConfig
        New configuration with identical fields and updated duckdb_materialize flag.
    """
    return IndexConfig(
        vec_dim=index.vec_dim,
        chunk_budget=index.chunk_budget,
        faiss_nlist=index.faiss_nlist,
        faiss_nprobe=index.faiss_nprobe,
        bm25_k1=index.bm25_k1,
        bm25_b=index.bm25_b,
        rrf_k=index.rrf_k,
        use_cuvs=index.use_cuvs,
        faiss_preload=index.faiss_preload,
        duckdb_materialize=enabled,
        preview_max_chars=index.preview_max_chars,
    )


def _reset_duckdb_catalog(db_path: Path) -> None:
    """Replace touch-based DuckDB placeholder with a valid, empty catalog."""
    if db_path.exists():
        db_path.unlink()
    with duckdb.connect(str(db_path)):
        pass


def _context_with_settings(
    context: ApplicationContext,
    settings: Settings,
) -> ApplicationContext:
    clone = Mock(spec=ApplicationContext)
    clone.paths = context.paths
    clone.settings = settings
    return cast("ApplicationContext", clone)


def test_check_result_as_payload_healthy() -> None:
    """Test CheckResult.as_payload() for healthy result."""
    # Arrange
    result = CheckResult(healthy=True)

    # Act
    payload = result.as_payload()

    # Assert
    assert payload == {"healthy": True}


def test_check_result_as_payload_unhealthy() -> None:
    """Test CheckResult.as_payload() for unhealthy result with detail."""
    # Arrange
    result = CheckResult(healthy=False, detail="FAISS index not found")

    # Act
    payload = result.as_payload()

    # Assert
    assert payload == {"healthy": False, "detail": "FAISS index not found"}


@pytest.mark.asyncio
async def test_readiness_probe_initialize(mock_context: ApplicationContext) -> None:
    """Test ReadinessProbe.initialize() calls refresh."""
    # Arrange
    probe = ReadinessProbe(mock_context)

    # Act
    await probe.initialize()

    # Assert
    snapshot = probe.snapshot()
    assert len(snapshot) > 0
    assert "repo_root" in snapshot


@pytest.mark.asyncio
async def test_readiness_probe_all_healthy(mock_context: ApplicationContext) -> None:
    """Test ReadinessProbe when all checks pass."""
    # Arrange
    probe = ReadinessProbe(mock_context)

    # Act
    results = await probe.refresh()

    # Assert
    assert results["repo_root"].healthy is True
    assert results["data_dir"].healthy is True
    assert results["vectors_dir"].healthy is True
    assert results["faiss_index"].healthy is True
    assert results["duckdb_catalog"].healthy is True
    assert results["scip_index"].healthy is True


@pytest.mark.asyncio
async def test_readiness_probe_materialize_reports_missing_table(
    mock_context: ApplicationContext,
) -> None:
    """Readiness should fail when materialization enabled but table missing."""
    existing_settings = mock_context.settings
    _reset_duckdb_catalog(mock_context.paths.duckdb_path)
    new_settings = Settings(
        vllm=existing_settings.vllm,
        paths=existing_settings.paths,
        index=_materialized_index_config(existing_settings.index, enabled=True),
        limits=existing_settings.limits,
        redis=existing_settings.redis,
        duckdb=existing_settings.duckdb,
        bm25=existing_settings.bm25,
        splade=existing_settings.splade,
        coderank=existing_settings.coderank,
        warp=existing_settings.warp,
        coderank_llm=existing_settings.coderank_llm,
    )
    probe = ReadinessProbe(_context_with_settings(mock_context, new_settings))

    results = await probe.refresh()
    duckdb_result = results["duckdb_catalog"]

    assert duckdb_result.healthy is False
    assert duckdb_result.detail is not None
    assert "chunks_materialized" in duckdb_result.detail


@pytest.mark.asyncio
async def test_readiness_probe_materialize_validates_index(
    mock_context: ApplicationContext,
) -> None:
    """Readiness passes when materialized table and index exist."""
    existing_settings = mock_context.settings
    _reset_duckdb_catalog(mock_context.paths.duckdb_path)
    new_settings = Settings(
        vllm=existing_settings.vllm,
        paths=existing_settings.paths,
        index=_materialized_index_config(existing_settings.index, enabled=True),
        limits=existing_settings.limits,
        redis=existing_settings.redis,
        duckdb=existing_settings.duckdb,
        bm25=existing_settings.bm25,
        splade=existing_settings.splade,
        coderank=existing_settings.coderank,
        warp=existing_settings.warp,
        coderank_llm=existing_settings.coderank_llm,
    )
    context = _context_with_settings(mock_context, new_settings)

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

    assert results["duckdb_catalog"].healthy is True


@pytest.mark.asyncio
async def test_readiness_probe_missing_faiss(mock_context: ApplicationContext) -> None:
    """Test ReadinessProbe when FAISS index is missing."""
    # Arrange
    mock_context.paths.faiss_index.unlink()
    probe = ReadinessProbe(mock_context)

    # Act
    results = await probe.refresh()

    # Assert
    assert results["faiss_index"].healthy is False
    assert results["faiss_index"].detail is not None
    assert "not found" in results["faiss_index"].detail.lower()


@pytest.mark.asyncio
async def test_readiness_probe_vllm_unreachable(
    mock_context: ApplicationContext,
) -> None:
    """Test ReadinessProbe when vLLM service is unreachable."""
    # Arrange
    probe = ReadinessProbe(mock_context)

    # Act - mock httpx to raise HTTPError
    with patch("httpx.Client") as mock_client:
        mock_instance = Mock()
        mock_instance.get.side_effect = httpx.HTTPError("Connection refused")
        mock_client.return_value.__enter__.return_value = mock_instance

        results = await probe.refresh()

    # Assert
    assert results["vllm_service"].healthy is False
    assert results["vllm_service"].detail is not None
    assert "unreachable" in results["vllm_service"].detail.lower()


@pytest.mark.asyncio
async def test_readiness_probe_caching(mock_context: ApplicationContext) -> None:
    """Test that ReadinessProbe caches results."""
    # Arrange
    probe = ReadinessProbe(mock_context)
    await probe.initialize()

    # Act - get snapshot without refresh
    snapshot1 = probe.snapshot()

    # Modify context (shouldn't affect cached results)
    mock_context.paths.faiss_index.unlink()

    snapshot2 = probe.snapshot()

    # Assert - cached results should be identical
    assert snapshot1 == snapshot2

    # Refresh should update cache
    await probe.refresh()
    snapshot3 = probe.snapshot()
    assert snapshot3["faiss_index"].healthy is False


@pytest.mark.asyncio
async def test_readiness_probe_shutdown(mock_context: ApplicationContext) -> None:
    """Test ReadinessProbe.shutdown() clears state."""
    # Arrange
    probe = ReadinessProbe(mock_context)
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
        assert result.healthy is True
        assert result.detail is None


def test_readiness_probe_check_directory_create() -> None:
    """Test _check_directory() with create=True."""
    # Arrange
    with tempfile.TemporaryDirectory() as tmpdir:
        new_dir = Path(tmpdir) / "new_subdir"

        # Act
        result = ReadinessProbe.check_directory(new_dir, create=True)

        # Assert
        assert result.healthy is True
        assert new_dir.exists()
        assert new_dir.is_dir()


def test_readiness_probe_check_file_exists() -> None:
    """Test _check_file() for existing file."""
    # Arrange
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        path = Path(tmpfile.name)

    try:
        # Act
        result = ReadinessProbe.check_file(path, description="test file")

        # Assert
        assert result.healthy is True
    finally:
        path.unlink()


def test_readiness_probe_check_file_optional() -> None:
    """Test check_file() with optional=True for missing file."""
    # Arrange
    path = Path("/nonexistent/file.txt")

    # Act
    result = ReadinessProbe.check_file(path, description="test file", optional=True)

    # Assert
    assert result.healthy is True  # Optional files don't fail readiness
    assert result.detail is not None
    assert "not found" in result.detail.lower()


def test_readiness_probe_check_file_required() -> None:
    """Test check_file() with optional=False for missing file."""
    # Arrange
    path = Path("/nonexistent/file.txt")

    # Act
    result = ReadinessProbe.check_file(path, description="test file", optional=False)

    # Assert
    assert result.healthy is False
    assert result.detail is not None
    assert "not found" in result.detail.lower()


def test_readiness_probe_check_vllm_invalid_url(
    mock_context: ApplicationContext,
) -> None:
    """Test _check_vllm_connection() with invalid URL."""
    # Arrange - create new settings with invalid URL
    invalid_vllm = VLLMConfig(base_url="not-a-valid-url")
    new_settings = Settings(
        vllm=invalid_vllm,
        paths=mock_context.settings.paths,
        index=mock_context.settings.index,
        limits=mock_context.settings.limits,
        redis=mock_context.settings.redis,
        duckdb=mock_context.settings.duckdb,
        bm25=mock_context.settings.bm25,
        splade=mock_context.settings.splade,
        coderank=mock_context.settings.coderank,
        warp=mock_context.settings.warp,
        coderank_llm=mock_context.settings.coderank_llm,
    )
    context = _context_with_settings(mock_context, new_settings)
    probe = ReadinessProbe(context)

    # Act
    result = probe.check_vllm_connection()

    # Assert
    assert result.healthy is False
    assert result.detail is not None
    assert "invalid" in result.detail.lower()


def test_readiness_probe_check_vllm_success(mock_context: ApplicationContext) -> None:
    """Test _check_vllm_connection() with successful health check."""
    # Arrange - create new settings with valid URL
    valid_vllm = VLLMConfig(base_url="http://localhost:8001/v1")
    new_settings = Settings(
        vllm=valid_vllm,
        paths=mock_context.settings.paths,
        index=mock_context.settings.index,
        limits=mock_context.settings.limits,
        redis=mock_context.settings.redis,
        duckdb=mock_context.settings.duckdb,
        bm25=mock_context.settings.bm25,
        splade=mock_context.settings.splade,
        coderank=mock_context.settings.coderank,
        warp=mock_context.settings.warp,
        coderank_llm=mock_context.settings.coderank_llm,
    )
    context = _context_with_settings(mock_context, new_settings)
    probe = ReadinessProbe(context)

    # Act - mock successful HTTP response
    with patch("httpx.Client") as mock_client:
        mock_response = Mock()
        mock_response.is_success = True
        mock_instance = Mock()
        mock_instance.get.return_value = mock_response
        mock_client.return_value.__enter__.return_value = mock_instance

        result = probe.check_vllm_connection()

    # Assert
    assert result.healthy is True


def test_readiness_probe_check_vllm_http_error(
    mock_context: ApplicationContext,
) -> None:
    """Test _check_vllm_connection() with HTTP error."""
    # Arrange - create new settings with valid URL
    valid_vllm = VLLMConfig(base_url="http://localhost:8001/v1")
    new_settings = Settings(
        vllm=valid_vllm,
        paths=mock_context.settings.paths,
        index=mock_context.settings.index,
        limits=mock_context.settings.limits,
        redis=mock_context.settings.redis,
        duckdb=mock_context.settings.duckdb,
        bm25=mock_context.settings.bm25,
        splade=mock_context.settings.splade,
        coderank=mock_context.settings.coderank,
        warp=mock_context.settings.warp,
        coderank_llm=mock_context.settings.coderank_llm,
    )
    context = _context_with_settings(mock_context, new_settings)
    probe = ReadinessProbe(context)

    # Act - mock HTTP error
    with patch("httpx.Client") as mock_client:
        mock_instance = Mock()
        mock_instance.get.side_effect = httpx.HTTPError("Connection refused")
        mock_client.return_value.__enter__.return_value = mock_instance

        result = probe.check_vllm_connection()

    # Assert
    assert result.healthy is False
    assert result.detail is not None
    assert "unreachable" in result.detail.lower()
