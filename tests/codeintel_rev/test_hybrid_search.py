from __future__ import annotations

from collections.abc import Sequence

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.hybrid_search import (
    ChannelHit,
    HybridSearchEngine,
    HybridSearchOptions,
)
from codeintel_rev.plugins.channels import Channel
from codeintel_rev.plugins.registry import ChannelRegistry
from msgspec import structs


class _StubChannel(Channel):
    def __init__(
        self,
        name: str,
        hits: Sequence[ChannelHit],
        *,
        requires: frozenset[str] | None = None,
        cost: float = 1.0,
    ) -> None:
        self.name = name
        self.cost = cost
        self.requires = requires or frozenset()
        self._hits = list(hits)
        self.calls = 0

    def search(self, query: str, limit: int) -> list[ChannelHit]:
        self.calls += 1
        assert query  # sanity check
        return list(self._hits[:limit])


def _build_engine(
    _monkeypatch: pytest.MonkeyPatch,
    _tmp_path,
    *,
    channels: Sequence[_StubChannel] | None = None,
    capabilities: Capabilities | None = None,
    index_overrides: dict[str, object] | None = None,
) -> HybridSearchEngine:
    settings = load_settings()
    if index_overrides:
        index_cfg = structs.replace(settings.index, **index_overrides)
        settings = structs.replace(settings, index=index_cfg)
    paths = resolve_application_paths(settings)
    registry = ChannelRegistry.from_channels(channels or [])
    return HybridSearchEngine(
        settings,
        paths,
        capabilities=capabilities or Capabilities(),
        registry=registry,
    )


def test_hybrid_search_engine_rrf_fuses_channels(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    bm25_stub = _StubChannel(
        "bm25",
        [
            ChannelHit(doc_id="102", score=7.0),
            ChannelHit(doc_id="201", score=6.0),
        ],
        requires=frozenset({"warp_index_present", "lucene_importable"}),
    )
    splade_stub = _StubChannel(
        "splade",
        [
            ChannelHit(doc_id="101", score=4.2),
        ],
        requires=frozenset({"lucene_importable", "onnxruntime_importable"}),
    )
    caps = Capabilities(
        warp_index_present=True,
        lucene_importable=True,
        onnxruntime_importable=True,
    )
    engine = _build_engine(
        monkeypatch,
        tmp_path,
        channels=[bm25_stub, splade_stub],
        capabilities=caps,
    )

    result = engine.search(
        "hybrid query",
        semantic_hits=[(101, 0.5), (102, 0.4)],
        limit=3,
    )

    doc_ids = [doc.doc_id for doc in result.docs]
    assert set(doc_ids[:2]) == {"101", "102"}
    assert result.channels == ["semantic", "bm25", "splade"]
    assert result.warnings == []
    assert ("semantic", 1, 0.5) in result.contributions["101"]
    assert ("splade", 1, 4.2) in result.contributions["101"]
    assert bm25_stub.calls == 1
    assert splade_stub.calls == 1


def test_hybrid_search_engine_respects_channel_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    bm25_stub = _StubChannel("bm25", [], requires=frozenset({"warp_index_present"}))
    splade_stub = _StubChannel("splade", [], requires=frozenset({"lucene_importable"}))
    engine = _build_engine(
        monkeypatch,
        tmp_path,
        channels=[bm25_stub, splade_stub],
        capabilities=Capabilities(warp_index_present=True, lucene_importable=True),
        index_overrides={"enable_bm25_channel": False, "enable_splade_channel": False},
    )

    result = engine.search(
        "query",
        semantic_hits=[(42, 0.1)],
        limit=1,
    )

    assert [doc.doc_id for doc in result.docs] == ["42"]
    assert result.channels == ["semantic"]
    assert result.warnings == []
    assert bm25_stub.calls == 0
    assert splade_stub.calls == 0


def test_hybrid_search_engine_accepts_extra_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = _build_engine(
        monkeypatch,
        tmp_path,
        channels=[],
        capabilities=Capabilities(),
        index_overrides={"enable_bm25_channel": False, "enable_splade_channel": False},
    )

    result = engine.search(
        "query",
        semantic_hits=[(1, 0.3), (2, 0.2)],
        limit=2,
        options=HybridSearchOptions(
            extra_channels={"warp": [ChannelHit(doc_id="999", score=5.0)]},
            weights={"semantic": 1.0, "warp": 2.0},
        ),
    )

    assert result.channels == ["semantic", "warp"]
    assert ("warp", 1, 5.0) in result.contributions["999"]


def test_hybrid_channel_skips_missing_capability(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    splade_stub = _StubChannel(
        "splade",
        [ChannelHit(doc_id="5", score=2.0)],
        requires=frozenset({"lucene_importable"}),
    )
    engine = _build_engine(
        monkeypatch,
        tmp_path,
        channels=[splade_stub],
        capabilities=Capabilities(lucene_importable=False),
    )

    result = engine.search("query", semantic_hits=[(5, 0.1)], limit=1)

    assert result.channels == ["semantic"]
    assert splade_stub.calls == 0


def test_hybrid_search_exposes_stage_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = _build_engine(
        monkeypatch,
        tmp_path,
        channels=[_StubChannel("bm25", [ChannelHit("1", 1.2)])],
    )
    result = engine.search("query", semantic_hits=[(1, 0.5)], limit=1)
    assert result.method is not None
    stages = result.method.get("stages")
    assert stages, "expected stage metadata in method payload"
    assert isinstance(stages, list)
    stage_dicts: list[dict[str, object]] = [stage for stage in stages if isinstance(stage, dict)]
    stage_names: set[str] = set()
    for stage in stage_dicts:
        name = stage.get("name")
        if isinstance(name, str):
            stage_names.add(name)
    assert "search.faiss" in stage_names
    assert any(name.startswith("fusion.") for name in stage_names)
