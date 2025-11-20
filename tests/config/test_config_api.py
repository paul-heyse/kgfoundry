"""Tests for the immutable config API."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest
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
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
    validate_config,
)


def _make_config(tmp_path: Path) -> AppConfig:
    """Create test AppConfig with default paths.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for paths.

    Returns
    -------
    AppConfig
        Configured AppConfig instance.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    paths = PathsConfig(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        cache_dir=repo_root / "cache",
        logs_dir=repo_root / "logs",
    )
    duckdb = DuckDBSettings(database=repo_root / "catalog.duckdb")
    faiss = FAISSSettings(index_path=repo_root / "index.faiss")
    search = SearchSettings()
    logging_cfg = LoggingSettings()
    bm25 = BM25Settings(
        corpus_json_dir=repo_root / "bm25_json",
        index_dir=repo_root / "bm25_index",
        threads=4,
        enabled=True,
        k1=0.9,
        b=0.4,
        rm3_enabled=False,
        rm3_fb_docs=10,
        rm3_fb_terms=10,
        rm3_original_query_weight=0.5,
        analyzer="code",
    )
    splade = SpladeSettings(
        model_id="splade-model",
        model_dir=repo_root / "models",
        onnx_dir=repo_root / "models" / "onnx",
        onnx_file="model.onnx",
        vectors_dir=repo_root / "vectors",
        index_dir=repo_root / "index",
        provider="CPUExecutionProvider",
        quantization=100,
        max_terms=1000,
        max_clause_count=2048,
        batch_size=8,
        threads=4,
        enabled=True,
        max_query_terms=64,
        prune_below=0.0,
        analyzer="wordpiece",
        static_prune_pct=0.0,
    )
    xtr = XTRSettings(
        model_id="nomic-ai/CodeRankEmbed",
        device="cuda",
        max_query_tokens=256,
        candidate_k=200,
        dim=768,
        dtype="float16",
        enable=False,
        mode="narrow",
    )
    embeddings = EmbeddingsSettings(
        provider="hf",
        model_name="hf/model",
        device="cpu",
        batch_size=32,
        micro_batch_size=16,
        normalize=False,
        max_tokens=2048,
        max_sequence_chars=4096,
        retry_max_attempts=2,
        retry_backoff_ms=100,
        max_pending_batches=4,
        max_wait_ms=5,
        allow_hf_fallback=False,
    )
    vllm = VLLMSettings(
        base_url="http://localhost:9000/v1",
        model="nomic-ai/nomic-embed-code",
        batch_size=32,
        embedding_dim=1024,
        timeout_s=30.0,
        run_mode="http",
        memory_utilization=0.8,
        max_num_batched_tokens=40000,
        normalize=True,
        embedding_mode="MEAN",
        max_concurrent_requests=2,
        task="embed",
    )
    index_cfg = IndexSettings()
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
        search=search,
        logging=logging_cfg,
    )


def test_app_config_is_immutable(tmp_path: Path) -> None:
    """Assignments should fail on frozen dataclasses."""
    cfg = _make_config(tmp_path)
    mutable_paths = cast("Any", cfg.paths)
    with pytest.raises(FrozenInstanceError):
        mutable_paths.repo_root = tmp_path


def test_validate_config_rejects_invalid_values(tmp_path: Path) -> None:
    """validate_config enforces positive numeric values."""
    cfg = _make_config(tmp_path)
    bad_k = replace(cfg, faiss=replace(cfg.faiss, default_k=0))
    with pytest.raises(ValueError, match="faiss\\.default_k"):
        validate_config(bad_k)
    bad_nprobe = replace(cfg, faiss=replace(cfg.faiss, default_nprobe=0))
    with pytest.raises(ValueError, match="faiss\\.default_nprobe"):
        validate_config(bad_nprobe)
    bad_refine = replace(cfg, faiss=replace(cfg.faiss, refine_k_factor=0.0))
    with pytest.raises(ValueError, match="faiss\\.refine_k_factor"):
        validate_config(bad_refine)
    bad_search = replace(cfg, search=replace(cfg.search, max_results=0))
    with pytest.raises(ValueError, match="search\\.max_results"):
        validate_config(bad_search)
    bad_embed = replace(cfg, embeddings=replace(cfg.embeddings, batch_size=0))
    with pytest.raises(ValueError, match="embeddings\\.batch_size"):
        validate_config(bad_embed)
    bad_vllm = replace(cfg, vllm=replace(cfg.vllm, batch_size=0))
    with pytest.raises(ValueError, match="vllm\\.batch_size"):
        validate_config(bad_vllm)
    bad_bm25 = replace(cfg, bm25=replace(cfg.bm25, threads=0))
    with pytest.raises(ValueError, match="bm25\\.threads"):
        validate_config(bad_bm25)
    bad_xtr = replace(cfg, xtr=replace(cfg.xtr, dim=0))
    with pytest.raises(ValueError, match="xtr\\.dim"):
        validate_config(bad_xtr)
