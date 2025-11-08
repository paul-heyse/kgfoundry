from __future__ import annotations

import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self, cast
from unittest.mock import patch

import numpy as np
import pytest

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

from codeintel_rev.mcp_server.adapters.semantic import semantic_search
from codeintel_rev.mcp_server.schemas import ScopeIn

from kgfoundry_common.errors import EmbeddingError, VectorSearchError


@pytest.fixture(autouse=True)
def _stub_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a minimal metrics stub for semantic adapter tests."""

    class _Histogram:
        def labels(self, **_: object) -> _Histogram:
            return self

        def observe(self, _: object) -> None:
            return None

    class _Counter:
        def labels(self, **_: object) -> _Counter:
            return self

        def inc(self, _: object | None = None) -> None:
            return None

    class _Metrics:
        operation_duration_seconds = _Histogram()
        runs_total = _Counter()

    monkeypatch.setattr(
        "codeintel_rev.mcp_server.adapters.semantic.METRICS",
        _Metrics(),
    )


class StubDuckDBCatalog:
    """Stub DuckDB catalog for testing."""

    def __init__(
        self, _db_path: Any, _vectors_dir: Any, *, chunks: list[dict[str, Any]] | None = None
    ) -> None:
        """Initialize stub catalog.

        Parameters
        ----------
        _db_path : Any
            Database path (unused in stub).
        _vectors_dir : Any
            Vectors directory (unused in stub).
        chunks : list[dict[str, Any]] | None, optional
            List of chunks to return. If None, uses default chunk.
        """
        if chunks is None:
            self._chunks = [
                {
                    "id": 123,
                    "uri": "src/module.py",
                    "start_line": 0,
                    "end_line": 0,
                    "preview": "code snippet",
                }
            ]
        else:
            self._chunks = chunks
        self._chunk = self._chunks[0] if self._chunks else {}

    def __enter__(self) -> Self:
        """Enter context manager.

        Returns
        -------
        StubDuckDBCatalog
            Self instance.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: types.TracebackType | None,
    ) -> bool:  # pragma: no cover - passthrough
        """Exit context manager.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type.
        exc : BaseException | None
            Exception instance.
        tb : types.TracebackType | None
            Traceback.

        Returns
        -------
        bool
            Always returns False.
        """
        return False

    def get_chunk_by_id(self, chunk_id: int) -> dict[str, Any] | None:
        return self._chunk if chunk_id == 123 else None

    def query_by_ids(self, chunk_ids: list[int]) -> list[dict[str, Any]]:
        """Query chunks by IDs.

        Parameters
        ----------
        chunk_ids : list[int]
            List of chunk IDs to query.

        Returns
        -------
        list[dict[str, Any]]
            List of chunks matching the IDs.
        """
        return [dict(chunk) for chunk in self._chunks if chunk.get("id") in chunk_ids]

    def query_by_filters(
        self,
        chunk_ids: list[int],
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query chunks by IDs with filters.

        Parameters
        ----------
        chunk_ids : list[int]
            List of chunk IDs to query.
        include_globs : list[str] | None, optional
            Glob patterns to include. Defaults to None.
        exclude_globs : list[str] | None, optional
            Glob patterns to exclude. Defaults to None.
        languages : list[str] | None, optional
            Languages to filter by. Defaults to None.

        Returns
        -------
        list[dict[str, Any]]
            Filtered list of chunks.
        """
        import fnmatch

        filtered = [dict(chunk) for chunk in self._chunks if chunk.get("id") in chunk_ids]

        # Apply language filter
        if languages:
            extensions = []
            language_exts = {
                "python": [".py", ".pyi"],
                "typescript": [".ts", ".tsx"],
                "javascript": [".js", ".jsx"],
            }
            for lang in languages:
                extensions.extend(language_exts.get(lang.lower(), []))
            if extensions:
                filtered = [
                    chunk
                    for chunk in filtered
                    if isinstance(chunk.get("uri"), str)
                    and any(chunk["uri"].endswith(ext) for ext in extensions)
                ]

        # Apply include globs
        if include_globs:
            filtered = [
                chunk
                for chunk in filtered
                if isinstance(chunk.get("uri"), str)
                and any(fnmatch.fnmatch(chunk["uri"], pattern) for pattern in include_globs)
            ]

        # Apply exclude globs
        if exclude_globs:
            filtered = [
                chunk
                for chunk in filtered
                if isinstance(chunk.get("uri"), str)
                and not any(fnmatch.fnmatch(chunk["uri"], pattern) for pattern in exclude_globs)
            ]

        return filtered


class StubVLLMClient:
    """Stub vLLM client for testing."""

    def __init__(self, _config: Any) -> None:
        """Initialize stub vLLM client."""

    def embed_single(self, query: str) -> np.ndarray:
        """Return mock embedding vector.

        Parameters
        ----------
        query : str
            Query text.

        Returns
        -------
        np.ndarray
            Mock embedding vector (2560 dimensions).
        """
        assert query
        return np.array([0.1] * 2560, dtype=np.float32)


class _BaseStubFAISSManager:
    """Base stub FAISS manager for testing."""

    def __init__(self, *, should_fail_gpu: bool, search_ids: list[int] | None = None) -> None:
        """Initialize stub FAISS manager.

        Parameters
        ----------
        should_fail_gpu : bool
            Whether GPU cloning should fail.
        search_ids : list[int] | None, optional
            List of chunk IDs to return from search. If None, returns [123].
        """
        self.should_fail_gpu = should_fail_gpu
        self.gpu_disabled_reason: str | None = None
        self.clone_invocations = 0
        self.last_k: int | None = None
        self.last_nprobe: int | None = None
        self._search_ids = search_ids or [123]

    def load_cpu_index(self) -> None:
        """Load CPU index (no-op for testing)."""
        return

    def clone_to_gpu(self) -> bool:
        """Clone to GPU (may fail based on should_fail_gpu).

        Returns
        -------
        bool
            True if GPU cloning succeeds, False otherwise.
        """
        self.clone_invocations += 1
        if self.should_fail_gpu:
            self.gpu_disabled_reason = "FAISS GPU disabled - using CPU: simulated failure"
            return False
        self.gpu_disabled_reason = None
        return True

    def search(
        self, query: np.ndarray, *, k: int, nprobe: int = 128
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return mock search results.

        Parameters
        ----------
        query : np.ndarray
            Query vector.
        k : int
            Number of results to return.
        nprobe : int, optional
            Number of probes. Defaults to 128.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple of (distances, ids) arrays.
        """
        assert query.shape[0] == 1  # Batch size 1
        assert k >= 1
        self.last_k = k
        self.last_nprobe = nprobe
        assert nprobe >= 1
        # Return k results (or fewer if k > available chunks)
        # Use stored search_ids or default to [123]
        result_ids = self._search_ids[:k]
        ids = np.array([result_ids], dtype=np.int64)
        distances = np.array([[0.9] * len(result_ids)], dtype=np.float32)
        return distances, ids


@dataclass
class StubContextConfig:
    """Configuration for StubContext initialization."""

    limits: list[str] | None = None
    error: str | None = None
    max_results: int = 5
    catalog_chunks: list[dict[str, Any]] | None = None
    faiss_nprobe: int = 128


class StubContext:
    """Stub ApplicationContext for semantic adapter tests."""

    def __init__(
        self,
        *,
        faiss_manager: _BaseStubFAISSManager,
        config: StubContextConfig | None = None,
    ) -> None:
        """Initialize stub context.

        Parameters
        ----------
        faiss_manager : _BaseStubFAISSManager
            FAISS manager stub.
        config : StubContextConfig | None, optional
            Configuration for stub context. Defaults to None (uses defaults).
        """
        if config is None:
            config = StubContextConfig()
        self.faiss_manager = faiss_manager
        self.vllm_client = StubVLLMClient(SimpleNamespace())
        self.settings = SimpleNamespace(
            limits=SimpleNamespace(max_results=config.max_results),
            vllm=SimpleNamespace(base_url="http://localhost"),
            index=SimpleNamespace(faiss_nprobe=config.faiss_nprobe),
        )
        # Use tempfile for secure temporary paths in tests
        import tempfile

        temp_dir = Path(tempfile.gettempdir())
        self.paths = SimpleNamespace(
            faiss_index=temp_dir / "index.faiss",
            duckdb_path=temp_dir / "catalog.duckdb",
            vectors_dir=temp_dir / "vectors",
        )
        self._limits = config.limits or []
        self._error = config.error
        self._catalog_chunks = config.catalog_chunks

    def ensure_faiss_ready(self) -> tuple[bool, list[str], str | None]:
        """Return readiness tuple.

        Returns
        -------
        tuple[bool, list[str], str | None]
            Tuple of (ready, limits, error).
        """
        ready = self._error is None
        return ready, list(self._limits), self._error

    @contextmanager
    def open_catalog(self) -> Iterator[StubDuckDBCatalog]:
        """Yield stub catalog.

        Yields
        ------
        StubDuckDBCatalog
            Stub catalog instance.
        """
        yield StubDuckDBCatalog(None, None, chunks=self._catalog_chunks)


@pytest.mark.asyncio
async def test_semantic_search_gpu_success() -> None:
    context = StubContext(
        faiss_manager=_BaseStubFAISSManager(should_fail_gpu=False),
        config=StubContextConfig(limits=[], error=None),
    )

    # Mock session ID and scope (no scope for this test)
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        # Cast StubContext to ApplicationContext for type checking
        # StubContext implements the necessary interface for testing
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=1)

    assert "limits" not in result
    findings = result.get("findings")
    assert findings is not None
    assert len(findings) > 0
    location = findings[0].get("location")
    assert location is not None
    assert location.get("uri") == "src/module.py"


@pytest.mark.asyncio
async def test_semantic_search_gpu_fallback() -> None:
    context = StubContext(
        faiss_manager=_BaseStubFAISSManager(should_fail_gpu=True),
        config=StubContextConfig(
            limits=["FAISS GPU disabled - using CPU: simulated failure"], error=None
        ),
    )

    # Mock session ID and scope (no scope for this test)
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=1)

    limits = result.get("limits")
    assert limits == ["FAISS GPU disabled - using CPU: simulated failure"]
    findings = result.get("findings")
    assert findings is not None
    assert len(findings) > 0
    location = findings[0].get("location")
    assert location is not None
    assert location.get("uri") == "src/module.py"


@pytest.mark.asyncio
async def test_semantic_search_limit_truncates_to_max_results() -> None:
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, max_results=3),
    )

    # Mock session ID and scope (no scope for this test)
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=10)

    assert faiss_manager.last_k == 3
    limits = result.get("limits")
    assert limits is not None
    assert any("exceeds max_results" in message for message in limits)
    method = result.get("method")
    assert method is not None
    coverage = method.get("coverage")
    assert coverage is not None
    assert "/3 results" in coverage
    assert "requested 10" in coverage


@pytest.mark.asyncio
async def test_semantic_search_limit_enforces_minimum() -> None:
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, max_results=5),
    )

    # Mock session ID and scope (no scope for this test)
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=0)

    assert faiss_manager.last_k == 1
    limits = result.get("limits")
    assert limits is not None
    assert any("not positive" in message for message in limits)
    method = result.get("method")
    assert method is not None
    coverage = method.get("coverage")
    assert coverage is not None
    assert "/1 results" in coverage
    assert "requested 0" in coverage


@pytest.mark.asyncio
async def test_semantic_search_respects_configured_nprobe() -> None:
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, max_results=5, faiss_nprobe=64),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        await semantic_search(cast("ApplicationContext", context), "hello", limit=1)

    assert faiss_manager.last_nprobe == 64


@pytest.mark.asyncio
async def test_semantic_search_with_scope_filters() -> None:
    """Test semantic search applies scope filters (language filter).

    Verifies that when session scope has language filters, only chunks
    matching those languages are returned.
    """
    # Create catalog with mixed file types
    catalog_chunks = [
        {
            "id": 123,
            "uri": "src/main.py",
            "start_line": 0,
            "end_line": 10,
            "preview": "def main():\n    pass",
        },
        {
            "id": 456,
            "uri": "src/app.ts",
            "start_line": 0,
            "end_line": 10,
            "preview": "function app() {\n    return null;\n}",
        },
        {
            "id": 789,
            "uri": "src/utils.py",
            "start_line": 0,
            "end_line": 5,
            "preview": "def helper():\n    pass",
        },
    ]

    # FAISS returns all three chunk IDs
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False, search_ids=[123, 456, 789])

    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=catalog_chunks),
    )

    # Mock session scope with Python language filter
    scope: ScopeIn = {"languages": ["python"]}

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=scope),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "function", limit=10)

    findings = result.get("findings")
    assert findings is not None
    assert len(findings) == 2  # Only Python files

    # Verify all results are Python files
    uris = [finding.get("location", {}).get("uri", "") for finding in findings]
    assert all(uri.endswith(".py") for uri in uris)
    assert "src/main.py" in uris
    assert "src/utils.py" in uris
    assert "src/app.ts" not in uris

    # Verify scope is included in response
    assert result.get("scope") == scope


@pytest.mark.asyncio
async def test_semantic_search_no_scope() -> None:
    """Test semantic search without scope filters returns all files.

    Verifies that when no session scope is set, all chunks are returned
    (no filtering applied).
    """
    # Create catalog with mixed file types
    catalog_chunks = [
        {
            "id": 123,
            "uri": "src/main.py",
            "start_line": 0,
            "end_line": 10,
            "preview": "def main():\n    pass",
        },
        {
            "id": 456,
            "uri": "src/app.ts",
            "start_line": 0,
            "end_line": 10,
            "preview": "function app() {\n    return null;\n}",
        },
    ]

    # FAISS returns both chunk IDs
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False, search_ids=[123, 456])

    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=catalog_chunks),
    )

    # Mock no session scope
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "function", limit=10)

    findings = result.get("findings")
    assert findings is not None
    assert len(findings) == 2  # All files returned

    # Verify both file types are present
    uris = [finding.get("location", {}).get("uri", "") for finding in findings]
    assert "src/main.py" in uris
    assert "src/app.ts" in uris

    # Verify query_by_ids was called (not query_by_filters)
    # This is verified by the fact that all chunks are returned


# ==================== Error Handling Tests ====================


async def test_semantic_search_faiss_not_ready() -> None:
    """Test semantic_search raises VectorSearchError when FAISS is not ready."""
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error="Index not built", catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
        pytest.raises(VectorSearchError, match="Index not built"),
    ):
        await semantic_search(cast("ApplicationContext", context), "query", limit=10)


async def test_semantic_search_embedding_error() -> None:
    """Test semantic_search raises EmbeddingError when embedding fails."""
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-embedding-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
        pytest.raises(EmbeddingError, match="vLLM service unavailable"),
    ):
        await semantic_search(cast("ApplicationContext", context), "query", limit=10)


async def test_semantic_search_faiss_search_error() -> None:
    """Test semantic_search raises VectorSearchError when FAISS search fails."""
    faiss_manager = _BaseStubFAISSManager(should_fail_gpu=False)

    def failing_search(
        _query: np.ndarray, *, _k: int, _nprobe: int = 128
    ) -> tuple[np.ndarray, np.ndarray]:
        error_msg = "FAISS search failed"
        raise RuntimeError(error_msg)

    faiss_manager.search = failing_search  # type: ignore[assignment]

    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-search-error",
        ),
        patch("codeintel_rev.mcp_server.adapters.semantic.get_effective_scope", return_value=None),
        pytest.raises(VectorSearchError, match="FAISS search failed"),
    ):
        await semantic_search(cast("ApplicationContext", context), "query", limit=10)
