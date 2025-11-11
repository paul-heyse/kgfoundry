from __future__ import annotations

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.hybrid_search import (
    HybridSearchEngine,
    HybridSearchOptions,
    HybridSearchTuning,
)
from codeintel_rev.plugins.registry import ChannelRegistry


def _build_engine(monkeypatch: pytest.MonkeyPatch, tmp_path) -> HybridSearchEngine:
    monkeypatch.setenv("HYBRID_ENABLE_BM25", "0")
    monkeypatch.setenv("HYBRID_ENABLE_SPLADE", "0")
    monkeypatch.setenv("BM25_INDEX_DIR", str(tmp_path / "bm25"))
    monkeypatch.setenv("SPLADE_INDEX_DIR", str(tmp_path / "splade"))
    monkeypatch.setenv("SPLADE_MODEL_DIR", str(tmp_path / "splade-model"))
    monkeypatch.setenv("SPLADE_ONNX_DIR", str(tmp_path / "splade-onnx"))
    settings = load_settings()
    paths = resolve_application_paths(settings)
    registry = ChannelRegistry.from_channels([])
    return HybridSearchEngine(
        settings=settings,
        paths=paths,
        capabilities=Capabilities(),
        registry=registry,
    )


def test_hybrid_engine_records_method_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = _build_engine(monkeypatch, tmp_path)
    result = engine.search(
        "explainable query",
        semantic_hits=[(101, 0.9)],
        limit=1,
        options=HybridSearchOptions(
            tuning=HybridSearchTuning(
                k=5,
                nprobe=32,
            )
        ),
    )
    assert result.method is not None
    assert "coverage" in result.method
