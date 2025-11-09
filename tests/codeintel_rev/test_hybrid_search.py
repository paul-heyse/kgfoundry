from __future__ import annotations

from collections.abc import Sequence

import pytest
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.hybrid_search import ChannelHit, HybridSearchEngine


class _StubProvider:
    def __init__(self, hits: Sequence[ChannelHit]) -> None:
        self.hits = list(hits)
        self.calls = 0

    def search(self, query: str, top_k: int) -> list[ChannelHit]:
        self.calls += 1
        assert query  # sanity check
        return list(self.hits[:top_k])


def _build_engine(monkeypatch: pytest.MonkeyPatch, tmp_path) -> HybridSearchEngine:
    monkeypatch.setenv("HYBRID_ENABLE_BM25", "1")
    monkeypatch.setenv("HYBRID_ENABLE_SPLADE", "1")
    monkeypatch.setenv("BM25_INDEX_DIR", str(tmp_path / "bm25"))
    monkeypatch.setenv("SPLADE_INDEX_DIR", str(tmp_path / "splade"))
    monkeypatch.setenv("SPLADE_MODEL_DIR", str(tmp_path / "splade-model"))
    monkeypatch.setenv("SPLADE_ONNX_DIR", str(tmp_path / "splade-onnx"))
    settings = load_settings()
    paths = resolve_application_paths(settings)
    return HybridSearchEngine(settings, paths)


def test_hybrid_search_engine_rrf_fuses_channels(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = _build_engine(monkeypatch, tmp_path)
    stub_bm25 = _StubProvider(
        [
            ChannelHit(doc_id="102", score=7.0),
            ChannelHit(doc_id="201", score=6.0),
        ]
    )
    stub_splade = _StubProvider(
        [
            ChannelHit(doc_id="101", score=4.2),
        ]
    )
    monkeypatch.setattr(engine, "_create_bm25_provider", lambda: stub_bm25)
    monkeypatch.setattr(engine, "_create_splade_provider", lambda: stub_splade)

    result = engine.search(
        "hybrid query",
        semantic_hits=[(101, 0.5), (102, 0.4)],
        limit=3,
    )

    doc_ids = [doc.doc_id for doc in result.docs]
    assert doc_ids[:2] == ["101", "102"]
    assert result.channels == ["semantic", "bm25", "splade"]
    assert result.warnings == []
    assert ("semantic", 1, 0.5) in result.contributions["101"]
    assert ("splade", 1, 4.2) in result.contributions["101"]
    assert stub_bm25.calls == 1
    assert stub_splade.calls == 1


def test_hybrid_search_engine_respects_channel_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("HYBRID_ENABLE_BM25", "0")
    monkeypatch.setenv("HYBRID_ENABLE_SPLADE", "0")
    monkeypatch.setenv("BM25_INDEX_DIR", str(tmp_path / "bm25"))
    monkeypatch.setenv("SPLADE_INDEX_DIR", str(tmp_path / "splade"))
    monkeypatch.setenv("SPLADE_MODEL_DIR", str(tmp_path / "splade-model"))
    monkeypatch.setenv("SPLADE_ONNX_DIR", str(tmp_path / "splade-onnx"))

    settings = load_settings()
    paths = resolve_application_paths(settings)
    engine = HybridSearchEngine(settings, paths)

    def _unexpected_call() -> None:
        pytest.fail("Channel loader should not be invoked when disabled")

    monkeypatch.setattr(engine, "_create_bm25_provider", _unexpected_call)
    monkeypatch.setattr(engine, "_create_splade_provider", _unexpected_call)

    result = engine.search(
        "query",
        semantic_hits=[(42, 0.1)],
        limit=1,
    )

    assert [doc.doc_id for doc in result.docs] == ["42"]
    assert result.channels == ["semantic"]
    assert result.warnings == []


def test_hybrid_search_engine_accepts_extra_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("HYBRID_ENABLE_BM25", "0")
    monkeypatch.setenv("HYBRID_ENABLE_SPLADE", "0")
    monkeypatch.setenv("BM25_INDEX_DIR", str(tmp_path / "bm25"))
    monkeypatch.setenv("SPLADE_INDEX_DIR", str(tmp_path / "splade"))
    monkeypatch.setenv("SPLADE_MODEL_DIR", str(tmp_path / "splade-model"))
    monkeypatch.setenv("SPLADE_ONNX_DIR", str(tmp_path / "splade-onnx"))
    settings = load_settings()
    paths = resolve_application_paths(settings)
    engine = HybridSearchEngine(settings, paths)

    result = engine.search(
        "query",
        semantic_hits=[(1, 0.3), (2, 0.2)],
        limit=2,
        extra_channels={"warp": [ChannelHit(doc_id="999", score=5.0)]},
        weights={"semantic": 1.0, "warp": 2.0},
    )

    assert result.channels == ["semantic", "warp"]
    assert result.docs[0].doc_id == "999"
    assert ("warp", 1, 5.0) in result.contributions["999"]
