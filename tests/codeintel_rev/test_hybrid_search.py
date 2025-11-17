"""Tests for hybrid search engine RRF fusion, channel coordination, and search behavior."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.hybrid_search import (
    HybridSearchContext,
    HybridSearchEngine,
    HybridSearchOptions,
    HybridSearchProviders,
)
from codeintel_rev.plugins.channels import Channel
from codeintel_rev.plugins.registry import ChannelRegistry
from codeintel_rev.retrieval.types import SearchHit
from msgspec import structs

from tests._helpers import assertions


class _StubChannel(Channel):
    """Minimal channel used to model capability requirements."""

    def __init__(
        self,
        name: str,
        *,
        requires: frozenset[str] | None = None,
        cost: float = 1.0,
    ) -> None:
        self.name = name
        self.cost = cost
        self.requires = requires or frozenset()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        msg = f"{self.name} channel search invoked without provider override"
        del query, limit
        raise AssertionError(msg)


@pytest.fixture(name="hybrid_engine_factory")
def _hybrid_engine_factory() -> Callable[..., tuple[HybridSearchEngine, dict[str, int]]]:
    """Return a factory that builds hybrid engines with stubbed providers.

    Returns
    -------
    Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
        Builder returning an engine instance and provider call counts.
    """

    def _factory(
        *,
        bm25_hits: Sequence[SearchHit] | None = None,
        splade_hits: Sequence[SearchHit] | None = None,
        capabilities: Capabilities | None = None,
        index_overrides: dict[str, object] | None = None,
    ) -> tuple[HybridSearchEngine, dict[str, int]]:
        settings = load_settings()
        if index_overrides:
            index_cfg = structs.replace(settings.index, **index_overrides)
            settings = structs.replace(settings, index=index_cfg)
        paths = resolve_application_paths(settings)
        call_counts: dict[str, int] = defaultdict(int)

        def _provider(
            name: str,
            hits: Sequence[SearchHit] | None,
        ) -> Callable[[str, int], Sequence[SearchHit]] | None:
            if hits is None:
                return None
            hits_snapshot = tuple(hits)

            def _run(_query: str, limit: int) -> Sequence[SearchHit]:
                call_counts[name] += 1
                if limit <= 0:
                    return []
                return list(hits_snapshot[:limit])

            return _run

        channels: list[Channel] = []
        if bm25_hits is not None:
            channels.append(
                _StubChannel(
                    "bm25",
                    requires=frozenset({"warp_index_present", "lucene_importable"}),
                )
            )
        if splade_hits is not None:
            channels.append(
                _StubChannel(
                    "splade",
                    requires=frozenset({"lucene_importable", "onnxruntime_importable"}),
                )
            )
        registry = ChannelRegistry.from_channels(channels)
        default_caps = capabilities or Capabilities(
            warp_index_present=True,
            lucene_importable=True,
            onnxruntime_importable=True,
        )
        providers = HybridSearchProviders(
            bm25=_provider("bm25", bm25_hits),
            splade=_provider("splade", splade_hits),
        )
        context = HybridSearchContext(
            capabilities=default_caps,
            registry=registry,
            providers=providers,
        )
        engine = HybridSearchEngine(
            settings=settings,
            paths=paths,
            context=context,
        )
        return engine, call_counts

    return _factory


def test_hybrid_search_engine_rrf_fuses_channels(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search engine fuses multiple channels using RRF (Reciprocal Rank Fusion)."""
    bm25_hits = [
        SearchHit(doc_id="102", rank=0, score=7.0, source="bm25"),
        SearchHit(doc_id="201", rank=1, score=6.0, source="bm25"),
    ]
    splade_hits = [SearchHit(doc_id="101", rank=0, score=4.2, source="splade")]
    caps = Capabilities(
        warp_index_present=True,
        lucene_importable=True,
        onnxruntime_importable=True,
    )
    engine, calls = hybrid_engine_factory(
        bm25_hits=bm25_hits,
        splade_hits=splade_hits,
        capabilities=caps,
    )

    result = engine.search(
        "hybrid query",
        semantic_hits=[(101, 0.5), (102, 0.4)],
        limit=3,
    )

    doc_ids = [doc.doc_id for doc in result.docs]
    assertions.expect_equal(set(doc_ids[:2]), {"101", "102"})
    assertions.expect_sequence_equal(result.channels, ["semantic", "bm25", "splade"])
    assertions.expect_equal(result.warnings, [])
    assertions.expect_in(("semantic", 1, 0.5), result.contributions["101"])
    assertions.expect_in(("splade", 1, 4.2), result.contributions["101"])
    assertions.expect_equal(calls["bm25"], 1)
    assertions.expect_equal(calls["splade"], 1)


def test_hybrid_search_engine_respects_channel_flags(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search engine respects channel enable/disable flags."""
    engine, calls = hybrid_engine_factory(
        bm25_hits=[],
        splade_hits=[],
        capabilities=Capabilities(warp_index_present=True, lucene_importable=True),
        index_overrides={"enable_bm25_channel": False, "enable_splade_channel": False},
    )

    result = engine.search(
        "query",
        semantic_hits=[(42, 0.1)],
        limit=1,
    )

    assertions.expect_sequence_equal([doc.doc_id for doc in result.docs], ["42"])
    assertions.expect_sequence_equal(result.channels, ["semantic"])
    assertions.expect_equal(result.warnings, [])
    assertions.expect_equal(calls["bm25"], 0)
    assertions.expect_equal(calls["splade"], 0)


def test_hybrid_search_engine_accepts_extra_channels(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search engine accepts extra channels via search options."""
    engine, _ = hybrid_engine_factory(
        capabilities=Capabilities(),
        index_overrides={"enable_bm25_channel": False, "enable_splade_channel": False},
    )

    result = engine.search(
        "query",
        semantic_hits=[(1, 0.3), (2, 0.2)],
        limit=2,
        options=HybridSearchOptions(
            extra_channels={"warp": [SearchHit(doc_id="999", rank=0, score=5.0, source="warp")]},
            weights={"semantic": 1.0, "warp": 2.0},
        ),
    )

    assertions.expect_sequence_equal(result.channels, ["semantic", "warp"])
    assertions.expect_in(("warp", 1, 5.0), result.contributions["999"])


def test_hybrid_channel_skips_missing_capability(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search engine skips channels when required capabilities are missing."""
    splade_hits = [SearchHit(doc_id="5", rank=0, score=2.0, source="splade")]
    engine, calls = hybrid_engine_factory(
        splade_hits=splade_hits,
        capabilities=Capabilities(lucene_importable=False),
    )

    result = engine.search("query", semantic_hits=[(5, 0.1)], limit=1)

    assertions.expect_sequence_equal(result.channels, ["semantic"])
    assertions.expect_equal(calls["splade"], 0)


def test_hybrid_search_falls_back_when_faiss_unavailable(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search falls back to other channels when FAISS is unavailable."""
    bm25_hits = [SearchHit(doc_id="5", rank=0, score=3.2, source="bm25")]
    engine, calls = hybrid_engine_factory(
        bm25_hits=bm25_hits,
        capabilities=Capabilities(warp_index_present=True, lucene_importable=True),
    )

    result = engine.search(
        "query",
        semantic_hits=[(5, 0.99)],
        limit=1,
        options=HybridSearchOptions(faiss_ready=False),
    )

    assertions.expect_sequence_equal(result.channels, ["bm25"])
    assertions.expect_true(
        any(msg.startswith("faiss_fallback:unavailable") for msg in result.warnings),
        reason="should warn about faiss fallback",
    )
    assertions.expect_equal(calls["bm25"], 1)


def test_hybrid_search_drops_low_semantic_scores(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search drops semantic hits below minimum score threshold."""
    bm25_hits = [SearchHit(doc_id="7", rank=0, score=4.5, source="bm25")]
    engine, _ = hybrid_engine_factory(
        bm25_hits=bm25_hits,
        index_overrides={"semantic_min_score": 0.8},
    )

    result = engine.search("query", semantic_hits=[(7, 0.2)], limit=1)

    assertions.expect_false("semantic" in result.channels, reason="semantic should be dropped")
    assertions.expect_sequence_equal(result.channels, ["bm25"])
    assertions.expect_true(
        any(msg.startswith("faiss_fallback:low_score") for msg in result.warnings),
        reason="should warn about low score",
    )


def test_hybrid_search_exposes_stage_metadata(
    hybrid_engine_factory: Callable[..., tuple[HybridSearchEngine, dict[str, int]]]
) -> None:
    """Test that hybrid search exposes stage metadata for observability."""
    bm25_hits = [SearchHit("1", rank=0, score=1.2, source="bm25")]
    engine, _ = hybrid_engine_factory(bm25_hits=bm25_hits)
    result = engine.search("query", semantic_hits=[(1, 0.5)], limit=1)
    assertions.expect_true(result.method is not None, reason="should have method metadata")
    if result.method is None:  # pragma: no cover - defensive
        pytest.fail("should have method metadata")
    retrieval = result.method.get("retrieval")
    assertions.expect_true(
        isinstance(retrieval, list) and bool(retrieval), reason="expected retrieval metadata"
    )
    coverage = result.method.get("coverage")
    assertions.expect_true(
        isinstance(coverage, str) and "results" in coverage,
        reason="expected coverage metadata in method payload",
    )
