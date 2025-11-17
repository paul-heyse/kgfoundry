"""Tests for hybrid search engine explainability and method metadata recording."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.config.utils import replace_settings, replace_struct
from codeintel_rev.io.hybrid_search import (
    HybridSearchContext,
    HybridSearchEngine,
    HybridSearchOptions,
    HybridSearchTuning,
)
from codeintel_rev.plugins.registry import ChannelRegistry

from tests._helpers import assertions


def _build_engine(tmp_path: Path) -> HybridSearchEngine:
    repo_root = tmp_path / "repo"
    (repo_root / "data" / "faiss").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").touch()
    (repo_root / "data" / "vectors").mkdir(parents=True, exist_ok=True)
    (repo_root / "index.scip.json").write_text("{}", encoding="utf-8")
    bm25_dir = repo_root / "indexes" / "bm25"
    bm25_dir.mkdir(parents=True, exist_ok=True)
    splade_index_dir = repo_root / "indexes" / "splade_v3_impact"
    splade_index_dir.mkdir(parents=True, exist_ok=True)
    splade_model_dir = repo_root / "models" / "splade-model"
    splade_model_dir.mkdir(parents=True, exist_ok=True)
    splade_onnx_dir = repo_root / "models" / "splade-model" / "onnx"
    splade_onnx_dir.mkdir(parents=True, exist_ok=True)

    base = load_settings()
    settings = replace_settings(
        base,
        paths=replace_struct(base.paths, repo_root=str(repo_root)),
        bm25=replace_struct(base.bm25, enabled=False, index_dir=str(bm25_dir)),
        splade=replace_struct(
            base.splade,
            enabled=False,
            index_dir=str(splade_index_dir),
            model_dir=str(splade_model_dir),
            onnx_dir=str(splade_onnx_dir),
        ),
    )
    paths = resolve_application_paths(settings)
    registry = ChannelRegistry.from_channels([])
    context = HybridSearchContext(
        capabilities=Capabilities(),
        registry=registry,
    )
    return HybridSearchEngine(
        settings=settings,
        paths=paths,
        context=context,
    )


def test_hybrid_engine_records_method_metadata(tmp_path: Path) -> None:
    """Test that hybrid search engine records method metadata for explainability."""
    engine = _build_engine(tmp_path)
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
    assertions.expect_true(result.method is not None, reason="result should have method metadata")
    if result.method is None:  # pragma: no cover - defensive
        pytest.fail("result should have method metadata")
    assertions.expect_in("coverage", result.method)
