"""Tests for the Settings compatibility shim."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.config.api import (
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    EmbeddingsSettings,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    SpladeOnnxQueryConfig,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)
from codeintel_rev.config.shim import settings_from_app_config

from tests._helpers import assertions


def _make_app_config(tmp_path: Path) -> AppConfig:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    paths = PathsConfig(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        cache_dir=repo_root / ".cache",
        logs_dir=repo_root / "logs",
    )
    duckdb = DuckDBSettings(database=repo_root / "catalog.duckdb")
    faiss = FAISSSettings(index_path=repo_root / "index.faiss")
    bm25 = BM25Settings(
        corpus_json_dir=repo_root / "bm25_json",
        index_dir=repo_root / "indexes" / "bm25",
        threads=6,
        enabled=False,
        k1=1.1,
        b=0.7,
        rm3_enabled=True,
        rm3_fb_docs=12,
        rm3_fb_terms=18,
        rm3_original_query_weight=0.45,
        analyzer="standard",
        stopwords=("a", "b"),
    )
    splade = SpladeSettings(
        model_id="splade-model",
        model_dir=repo_root / "models" / "splade",
        onnx_dir=repo_root / "models" / "splade" / "onnx",
        onnx_file="model.onnx",
        vectors_dir=repo_root / "vectors",
        index_dir=repo_root / "indexes" / "splade",
        provider="CPUExecutionProvider",
        quantization=150,
        max_terms=2000,
        max_clause_count=4096,
        batch_size=64,
        threads=12,
        enabled=False,
        max_query_terms=32,
        prune_below=0.25,
        analyzer="wordpiece",
        static_prune_pct=0.05,
        onnx_query=SpladeOnnxQueryConfig(
            enabled=True,
            model_path=repo_root / "models" / "splade" / "onnx-query.onnx",
            tokenizer_name="splade-tokenizer",
            output_name="scores",
            input_ids_name="input_ids",
            attention_mask_name="attention_mask",
            providers=("CUDAExecutionProvider",),
            topn=8,
            min_weight=0.1,
            normalize=True,
            format="map",
        ),
    )
    xtr = XTRSettings(enable=True, dim=512, dtype="float32", mode="wide")
    embeddings = EmbeddingsSettings()
    vllm = VLLMSettings()
    index_cfg = IndexSettings(
        enable_bm25_channel=bm25.enabled,
        bm25_k1=bm25.k1,
        bm25_b=bm25.b,
        enable_splade_channel=splade.enabled,
    )
    return AppConfig(
        version="1.0",
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        bm25=bm25,
        splade=splade,
        xtr=xtr,
        index=index_cfg,
        embeddings=embeddings,
        vllm=vllm,
        search=SearchSettings(),
        logging=LoggingSettings(),
    )


def test_settings_from_app_config_updates_paths_and_splade(tmp_path: Path) -> None:
    """The shim should copy AppConfig data into legacy Settings structs."""
    cfg = _make_app_config(tmp_path)
    settings = settings_from_app_config(cfg)
    assertions.expect_equal(settings.paths.repo_root, str(cfg.paths.repo_root))
    assertions.expect_equal(settings.paths.faiss_index, str(cfg.faiss.index_path))
    assertions.expect_equal(settings.bm25.corpus_json_dir, str(cfg.bm25.corpus_json_dir))
    assertions.expect_equal(settings.bm25.index_dir, str(cfg.bm25.index_dir))
    assertions.expect_equal(settings.bm25.threads, cfg.bm25.threads)
    assertions.expect_equal(settings.bm25.analyzer, cfg.bm25.analyzer)
    assertions.expect_sequence_equal(list(settings.bm25.stopwords), list(cfg.bm25.stopwords))
    assertions.expect_equal(settings.splade.model_dir, str(cfg.splade.model_dir))
    assertions.expect_equal(settings.splade.index_dir, str(cfg.splade.index_dir))
    assertions.expect_equal(settings.splade.enabled, cfg.splade.enabled)
    onnx_cfg = settings.splade.onnx_query
    assertions.expect_true(onnx_cfg is not None, reason="Expected ONNX query config")
    if onnx_cfg is not None and cfg.splade.onnx_query is not None:
        assertions.expect_equal(
            onnx_cfg.model_path,
            str(cfg.splade.onnx_query.model_path),
        )
    assertions.expect_equal(settings.xtr.enable, cfg.xtr.enable)
    assertions.expect_equal(settings.xtr.dim, cfg.xtr.dim)
    assertions.expect_equal(settings.xtr.mode, cfg.xtr.mode)
