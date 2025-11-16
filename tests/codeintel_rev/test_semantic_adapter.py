from __future__ import annotations

import types
from collections.abc import Iterator, Sequence
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

from codeintel_rev.io.duckdb_catalog import StructureAnnotations
from codeintel_rev.mcp_server.adapters.semantic import semantic_search
from codeintel_rev.mcp_server.schemas import ScopeIn

from kgfoundry_common.errors import EmbeddingError
from tests._helpers import assertions


class StubDuckDBCatalog:
    """Stub DuckDB catalog for testing.

    Parameters
    ----------
    _db_path : Any
        Database path (unused in stub).
    _vectors_dir : Any
        Vectors directory (unused in stub).
    chunks : list[dict[str, Any]] | None, optional
        List of chunks to return. If None, uses default chunk.
    """

    def __init__(
        self,
        _db_path: Any,
        _vectors_dir: Any,
        *,
        chunks: list[dict[str, Any]] | None = None,
    ) -> None:
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
        Self
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

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, StructureAnnotations]:
        annotations: dict[int, StructureAnnotations] = {}
        for chunk_id in ids:
            annotations[int(chunk_id)] = StructureAnnotations(
                uri=str(self._chunk.get("uri", "")),
                symbol_hits=("stub.symbol",),
                ast_node_kinds=("FunctionDef",),
                cst_matches=(),
            )
        return annotations


class StubVLLMClient:
    """Stub vLLM client for testing.

    Parameters
    ----------
    _config : Any
        Configuration (unused in stub).
    """

    def __init__(self, _config: Any) -> None:
        pass

    def embed_single(self, query: str) -> np.ndarray:
        """Return mock embedding vector.

        Parameters
        ----------
        query : str
            Query text.

        Returns
        -------
        np.ndarray
            Mock embedding vector (3584 dimensions).
        """
        assertions.expect_true(bool(query), reason="query should be non-empty")
        return np.array([0.1] * 3584, dtype=np.float32)


class _BaseStubFAISSManager:
    """Base stub FAISS manager for testing CPU-only execution.

    Parameters
    ----------
    search_ids : list[int] | None, optional
        List of chunk IDs to return from search. If None, returns [123].
    """

    def __init__(self, *, search_ids: list[int] | None = None) -> None:
        self.last_k: int | None = None
        self.last_nprobe: int | None = None
        self.last_ef_search: int | None = None
        self.last_quantizer_ef_search: int | None = None
        self.last_k_factor: float | None = None
        self._search_ids = search_ids or [123]
        self._last_catalog: object | None = None

    def load_cpu_index(self) -> None:
        """Load CPU index (no-op for testing)."""
        return

    def search(
        self,
        query: np.ndarray,
        *,
        k: int,
        nprobe: int = 128,
        runtime: object | None = None,
        catalog: object | None = None,
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
        runtime : object | None, optional
            Runtime override bundle captured for verification in tests.
        catalog : object | None, optional
            Catalog reference mirroring the production signature. Captured for
            verification during tests.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple of (distances, ids) arrays.
        """
        assertions.expect_equal(query.shape[0], 1, reason="Batch size should be 1")
        assertions.expect_true(k >= 1, reason="k should be at least 1")
        self.last_k = k
        self.last_nprobe = nprobe
        self.last_ef_search = getattr(runtime, "ef_search", None)
        self.last_quantizer_ef_search = getattr(runtime, "quantizer_ef_search", None)
        self.last_k_factor = getattr(runtime, "k_factor", None)
        if catalog is not None:
            self._last_catalog = catalog
        assertions.expect_true(nprobe >= 1, reason="nprobe should be at least 1")
        # Return k results (or fewer if k > available chunks)
        # Use stored search_ids or default to [123]
        result_ids = self._search_ids[:k]
        ids = np.array([result_ids], dtype=np.int64)
        distances = np.array([[0.9] * len(result_ids)], dtype=np.float32)
        return distances, ids


class _DefaultStubHybridEngine:
    """Default hybrid engine stub that yields no additional channels."""

    def search(
        self,
        query: str,
        *,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: Any | None = None,
    ) -> SimpleNamespace:
        del query, semantic_hits, limit, options
        return SimpleNamespace(
            docs=[],
            contributions={},
            channels=[],
            warnings=[],
            method=None,
        )


@dataclass(frozen=True)
class StubContextConfig:
    """Configuration for StubContext initialization."""

    limits: list[str] | None = None
    error: str | None = None
    max_results: int = 5
    semantic_overfetch_multiplier: int = 2
    catalog_chunks: list[dict[str, Any]] | None = None
    faiss_nprobe: int = 128
    hybrid_engine: Any | None = None
    enable_bm25_channel: bool = True
    enable_splade_channel: bool = True
    hybrid_top_k_per_channel: int = 50
    rrf_k: int = 60


class StubContext:
    """Stub ApplicationContext for semantic adapter tests.

    Parameters
    ----------
    faiss_manager : _BaseStubFAISSManager
        FAISS manager stub.
    config : StubContextConfig | None, optional
        Configuration for stub context. Defaults to None (uses defaults).
    """

    def __init__(
        self,
        *,
        faiss_manager: _BaseStubFAISSManager,
        config: StubContextConfig | None = None,
    ) -> None:
        if config is None:
            config = StubContextConfig()
        self.faiss_manager = faiss_manager
        self.vllm_client = StubVLLMClient(SimpleNamespace())
        self.settings = SimpleNamespace(
            limits=SimpleNamespace(
                max_results=config.max_results,
                semantic_overfetch_multiplier=config.semantic_overfetch_multiplier,
            ),
            vllm=SimpleNamespace(base_url="http://localhost"),
            index=SimpleNamespace(
                faiss_nprobe=config.faiss_nprobe,
                enable_bm25_channel=config.enable_bm25_channel,
                enable_splade_channel=config.enable_splade_channel,
                hybrid_top_k_per_channel=config.hybrid_top_k_per_channel,
                rrf_k=config.rrf_k,
                semantic_min_score=0.0,
            ),
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
        self._hybrid_engine = config.hybrid_engine or _DefaultStubHybridEngine()

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

    def get_hybrid_engine(self) -> Any:
        """Return configured hybrid engine stub.

        Returns
        -------
        Any
            Hybrid engine stub instance.
        """
        return self._hybrid_engine


@pytest.mark.asyncio
async def test_semantic_search_applies_scope_faiss_tuning() -> None:
    manager = _BaseStubFAISSManager()
    context = StubContext(
        faiss_manager=manager,
        config=StubContextConfig(limits=[], error=None),
    )
    scope = {"faiss_tuning": {"nprobe": 256, "ef_search": 96, "k_factor": 2.0}}
    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="session-tune",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=scope,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello scope", limit=1)

    assertions.expect_true(bool(result.get("findings")), reason="should have findings")
    assertions.expect_equal(manager.last_nprobe, 256)
    assertions.expect_equal(manager.last_ef_search, 96)
    assertions.expect_almost_equal(cast("float", manager.last_k_factor), 2.0)


@pytest.mark.asyncio
async def test_semantic_search_limit_truncates_to_max_results() -> None:
    faiss_manager = _BaseStubFAISSManager()
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
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=10)

    assertions.expect_equal(faiss_manager.last_k, 3)
    limits = result.get("limits")
    assertions.expect_true(limits is not None, reason="should have limits")
    assertions.expect_true(
        any("exceeds max_results" in message for message in cast("list[str]", limits)),
        reason="should warn about exceeding max_results",
    )
    method = result.get("method")
    assertions.expect_true(method is not None, reason="should have method")
    coverage = method.get("coverage")
    assertions.expect_true(coverage is not None, reason="should have coverage")
    assertions.expect_in("/3 results", cast("str", coverage))
    assertions.expect_in("requested 10", cast("str", coverage))


@pytest.mark.asyncio
async def test_semantic_search_limit_enforces_minimum() -> None:
    faiss_manager = _BaseStubFAISSManager()
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
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hello", limit=0)

    assertions.expect_equal(faiss_manager.last_k, 1)
    limits = result.get("limits")
    assertions.expect_true(limits is not None, reason="should have limits")
    assertions.expect_true(
        any("not positive" in message for message in cast("list[str]", limits)),
        reason="should warn about non-positive limit",
    )
    method = result.get("method")
    assertions.expect_true(method is not None, reason="should have method")
    coverage = method.get("coverage")
    assertions.expect_true(coverage is not None, reason="should have coverage")
    assertions.expect_in("/1 results", cast("str", coverage))
    assertions.expect_in("requested 0", cast("str", coverage))


@pytest.mark.asyncio
async def test_semantic_search_respects_configured_nprobe() -> None:
    faiss_manager = _BaseStubFAISSManager()
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, max_results=5, faiss_nprobe=64),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-123",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        await semantic_search(cast("ApplicationContext", context), "hello", limit=1)

    assertions.expect_equal(faiss_manager.last_nprobe, 64)


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
    faiss_manager = _BaseStubFAISSManager(search_ids=[123, 456, 789])

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
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=scope,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "function", limit=10)

    findings = result.get("findings")
    assertions.expect_true(findings is not None, reason="should have findings")
    assertions.expect_equal(len(findings), 2)  # Only Python files

    # Verify all results are Python files
    uris = [finding.get("location", {}).get("uri", "") for finding in findings]
    assertions.expect_true(
        all(uri.endswith(".py") for uri in uris), reason="all results should be Python files"
    )
    assertions.expect_in("src/main.py", uris)
    assertions.expect_in("src/utils.py", uris)
    assertions.expect_false("src/app.ts" in uris, reason="TypeScript files should be filtered out")

    # Verify scope is included in response
    assertions.expect_equal(result.get("scope"), scope)


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
    faiss_manager = _BaseStubFAISSManager(search_ids=[123, 456])

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
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "function", limit=10)

    findings = result.get("findings")
    assertions.expect_true(findings is not None, reason="should have findings")
    assertions.expect_equal(len(findings), 2)  # All files returned

    # Verify both file types are present
    uris = [finding.get("location", {}).get("uri", "") for finding in findings]
    assertions.expect_in("src/main.py", uris)
    assertions.expect_in("src/app.ts", uris)

    # Verify query_by_ids was called (not query_by_filters)
    # This is verified by the fact that all chunks are returned


@pytest.mark.asyncio
async def test_semantic_search_hybrid_merges_channels() -> None:
    class _HybridStub:
        def search(
            self,
            query: str,
            *,
            semantic_hits: Sequence[tuple[int, float]],
            limit: int,
            options: Any | None = None,
        ) -> SimpleNamespace:
            del query, semantic_hits, limit, options
            docs = [
                SimpleNamespace(doc_id="101", score=0.42),
                SimpleNamespace(doc_id="102", score=0.35),
            ]
            contributions = {
                "101": [("semantic", 1, 0.1), ("bm25", 2, 8.5)],
                "102": [("splade", 1, 12.0)],
            }
            return SimpleNamespace(
                docs=docs,
                contributions=contributions,
                channels=["semantic", "bm25", "splade"],
                warnings=["bm25 warmed up"],
                method=None,
            )

    faiss_manager = _BaseStubFAISSManager(search_ids=[101, 102])
    chunks = [
        {"id": 101, "uri": "src/a.py", "start_line": 0, "end_line": 2, "preview": "a"},
        {"id": 102, "uri": "src/b.py", "start_line": 5, "end_line": 9, "preview": "b"},
    ]
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(
            limits=[],
            error=None,
            catalog_chunks=chunks,
            hybrid_engine=_HybridStub(),
        ),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="hybrid-session",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "hybrid query", limit=2)

    answer = result.get("answer")
    assertions.expect_true(answer is not None, reason="should have answer")
    assertions.expect_true(
        answer.startswith("Found 2 hybrid"), reason="answer should start with Found 2 hybrid"
    )
    limits = result.get("limits")
    assertions.expect_true(limits is not None, reason="should have limits")
    assertions.expect_in("bm25 warmed up", cast("list[str]", limits))
    findings = result.get("findings")
    assertions.expect_true(findings is not None, reason="should have findings")
    assertions.expect_equal(findings[0].get("chunk_id"), 101)
    why_message = findings[0].get("why")
    assertions.expect_true(why_message is not None, reason="should have why message")
    assertions.expect_in("Hybrid RRF", cast("str", why_message))
    assertions.expect_in("bm25", cast("str", why_message))
    method = result.get("method")
    assertions.expect_true(method is not None, reason="should have method")
    retrieval = method.get("retrieval")
    assertions.expect_true(retrieval is not None, reason="should have retrieval")
    retrieval_set = set(cast("list[str]", retrieval))
    missing_channels = {"semantic", "faiss", "bm25", "splade"} - retrieval_set
    assertions.expect_false(bool(missing_channels), reason="all channels should be present")


# ==================== Error Handling Tests ====================


async def test_semantic_search_faiss_not_ready() -> None:
    """Test semantic_search falls back when FAISS is not ready."""
    faiss_manager = _BaseStubFAISSManager()
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error="Index not built", catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "query", limit=10)
    limits = result.get("limits") or []
    joined_limits = " ".join(cast("list[str]", limits))
    assertions.expect_in("faiss_fallback", joined_limits)
    assertions.expect_equal(result.get("findings"), [])


async def test_semantic_search_embedding_error() -> None:
    """Test semantic_search raises EmbeddingError when embedding fails."""
    faiss_manager = _BaseStubFAISSManager()
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-embedding-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
        patch.object(
            context.vllm_client,
            "embed_single",
            side_effect=RuntimeError("vLLM service unavailable"),
        ),
        pytest.raises(EmbeddingError, match="vLLM service unavailable"),
    ):
        await semantic_search(cast("ApplicationContext", context), "query", limit=10)


async def test_semantic_search_faiss_search_error() -> None:
    """Test semantic_search falls back when FAISS search fails."""
    faiss_manager = _BaseStubFAISSManager()
    context = StubContext(
        faiss_manager=faiss_manager,
        config=StubContextConfig(limits=[], error=None, catalog_chunks=None),
    )

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_session_id",
            return_value="test-session-search-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.semantic.get_effective_scope",
            return_value=None,
        ),
        patch.object(
            faiss_manager,
            "search",
            side_effect=RuntimeError("FAISS search failed"),
        ),
    ):
        result = await semantic_search(cast("ApplicationContext", context), "query", limit=10)
    limits = result.get("limits") or []
    assertions.expect_true(
        any("faiss_fallback" in entry for entry in cast("list[str]", limits)),
        reason="should have faiss_fallback in limits",
    )
    assertions.expect_equal(result.get("findings"), [])
