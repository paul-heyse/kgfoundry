"""Unit tests for the sparse retrieval engine surfaces."""

from __future__ import annotations

import numpy as np
from codeintel_rev.io.bm25_engine import BM25Backend, BM25Engine
from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.io.splade_engine import (
    SpladeBackend,
    SPLADEEngine,
    SpladeQueryRepresentation,
)

from tests._helpers import assertions


class _StubSpladeBackend(SpladeBackend):
    def __init__(self) -> None:
        self.encode_calls = 0
        self.last_k: int | None = None

    def encode_query(self, text: str) -> np.ndarray:
        """Encode query text and track call count.

        Parameters
        ----------
        text : str
            Query text (unused).

        Returns
        -------
        np.ndarray
            Stub embedding array of shape (1, 2).
        """
        self.encode_calls += 1
        _ = text
        return np.ones((1, 2), dtype=np.float32)

    def search(self, query_vec: SpladeQueryRepresentation, k: int) -> list[tuple[int, float]]:
        """Search with query vector and record k parameter.

        Parameters
        ----------
        query_vec : SpladeQueryRepresentation
            Query vector representation (unused).
        k : int
            Number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            Stub search results [(10, 1.2), (20, 0.4)].
        """
        self.last_k = k
        _ = query_vec
        return [(10, 1.2), (20, 0.4)]


class _StubBM25Backend(BM25Backend):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query_text: str, k: int) -> list[tuple[int, float]]:
        """Search with query text and track call count.

        Parameters
        ----------
        query_text : str
            Query text (unused).
        k : int
            Number of results (unused).

        Returns
        -------
        list[tuple[int, float]]
            Stub search results [(5, 0.9), (15, 0.2)].
        """
        _ = (query_text, k)
        self.calls += 1
        return [(5, 0.9), (15, 0.2)]


def test_splade_engine_normalizes_backend_results() -> None:
    """SPLADE engine should normalize backend outputs."""
    engine = SPLADEEngine(_StubSpladeBackend())

    hits = engine.search("hybrid search refactor", k=1)

    assertions.expect_equal(hits, [(10, 1.2)])


def test_bm25_engine_coerces_backend_values() -> None:
    """BM25 engine should coerce backend return values to correct types."""

    class _StringBackend(BM25Backend):
        def __init__(self) -> None:
            self.calls = 0

        def search(self, query_text: str, k: int) -> list[tuple[int, float]]:
            """Search with query text and track call count.

            Parameters
            ----------
            query_text : str
                Query text (unused).
            k : int
                Number of results (unused).

            Returns
            -------
            list[tuple[int, float]]
                Stub search results [(9, 3.14), (11, 2.0)].
            """
            _ = (query_text, k)
            self.calls += 1
            return [(9, 3.14), (11, 2.0)]

    engine = BM25Engine(_StringBackend())

    hits = engine.search("sparse retrieval", k=2)

    assertions.expect_equal(hits[0], (9, 3.14))
    assertions.expect_equal(len(hits), 2)


def test_hybrid_engine_combines_channels() -> None:
    """Hybrid engine should combine BM25/SPLADE hits with semantic input."""
    hybrid = HybridSearchEngine(
        bm25=BM25Engine(_StubBM25Backend()),
        splade=SPLADEEngine(_StubSpladeBackend()),
    )
    semantic_hits = [(99, 2.5)]
    options = HybridSearchOptions(fusion_k=2, per_channel_k=2, weights={"semantic": 2.0})

    result = hybrid.search(
        query="functions to refactor",
        semantic_hits=semantic_hits,
        limit=2,
        options=options,
    )

    assertions.expect_equal(len(result.docs), 2)
    assertions.expect_true(result.method is not None)
    assertions.expect_in("bm25", result.channels)
