"""Compatibility helpers for bridging AppConfig to legacy Settings structs."""

from __future__ import annotations

from msgspec import structs

from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.settings import (
    BM25Config as LegacyBM25Config,
)
from codeintel_rev.config.settings import (
    EmbeddingsConfig as LegacyEmbeddingsConfig,
)
from codeintel_rev.config.settings import (
    PRFConfig as LegacyPRFConfig,
)
from codeintel_rev.config.settings import (
    Settings,
    load_settings,
)
from codeintel_rev.config.settings import (
    SpladeConfig as LegacySpladeConfig,
)
from codeintel_rev.config.settings import (
    SpladeOnnxQueryConfig as LegacySpladeOnnxQueryConfig,
)
from codeintel_rev.config.settings import (
    VLLMConfig as LegacyVLLMConfig,
)
from codeintel_rev.config.settings import (
    VLLMEmbeddingMode as LegacyVLLMEmbeddingMode,
)
from codeintel_rev.config.settings import (
    VLLMRunMode as LegacyVLLMRunMode,
)
from codeintel_rev.config.settings import (
    XTRConfig as LegacyXTRConfig,
)


def _convert_splade_config(app_config: AppConfig) -> LegacySpladeConfig:
    """Convert AppConfig SPLADE settings to legacy SpladeConfig format.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing SPLADE settings to convert.

    Returns
    -------
    LegacySpladeConfig
        Legacy msgspec-based SPLADE configuration struct with all fields
        populated from app_config.splade, including optional ONNX query
        encoder configuration if present.
    """
    splade = app_config.splade
    onnx_query_cfg = splade.onnx_query
    legacy_onnx = None
    if onnx_query_cfg is not None:
        legacy_onnx = LegacySpladeOnnxQueryConfig(
            enabled=onnx_query_cfg.enabled,
            model_path=str(onnx_query_cfg.model_path) if onnx_query_cfg.model_path else None,
            tokenizer_name=onnx_query_cfg.tokenizer_name,
            output_name=onnx_query_cfg.output_name,
            input_ids_name=onnx_query_cfg.input_ids_name,
            attention_mask_name=onnx_query_cfg.attention_mask_name,
            providers=onnx_query_cfg.providers,
            topn=onnx_query_cfg.topn,
            min_weight=onnx_query_cfg.min_weight,
            normalize=onnx_query_cfg.normalize,
            format=onnx_query_cfg.format,
        )
    return LegacySpladeConfig(
        model_id=splade.model_id,
        model_dir=str(splade.model_dir),
        onnx_dir=str(splade.onnx_dir),
        onnx_file=splade.onnx_file,
        vectors_dir=str(splade.vectors_dir),
        index_dir=str(splade.index_dir),
        provider=splade.provider,
        quantization=splade.quantization,
        max_terms=splade.max_terms,
        max_clause_count=splade.max_clause_count,
        batch_size=splade.batch_size,
        threads=splade.threads,
        enabled=splade.enabled,
        max_query_terms=splade.max_query_terms,
        prune_below=splade.prune_below,
        analyzer=splade.analyzer,
        static_prune_pct=splade.static_prune_pct,
        onnx_query=legacy_onnx,
    )


def _convert_embeddings_config(app_config: AppConfig) -> LegacyEmbeddingsConfig:
    """Convert Embeddings settings to legacy struct.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing EmbeddingsSettings to convert.

    Returns
    -------
    LegacyEmbeddingsConfig
        Legacy msgspec-based embeddings configuration struct with all fields
        populated from app_config.embeddings.
    """
    embeddings = app_config.embeddings
    return LegacyEmbeddingsConfig(
        provider=embeddings.provider,
        model_name=embeddings.model_name,
        device=embeddings.device,
        batch_size=embeddings.batch_size,
        micro_batch_size=embeddings.micro_batch_size,
        normalize=embeddings.normalize,
        max_tokens=embeddings.max_tokens,
        max_sequence_chars=embeddings.max_sequence_chars,
        retry_max_attempts=embeddings.retry_max_attempts,
        retry_backoff_ms=embeddings.retry_backoff_ms,
        max_pending_batches=embeddings.max_pending_batches,
        max_wait_ms=embeddings.max_wait_ms,
        allow_hf_fallback=embeddings.allow_hf_fallback,
    )


def _convert_vllm_config(app_config: AppConfig) -> LegacyVLLMConfig:
    """Convert vLLM settings to legacy struct.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing VLLMSettings to convert.

    Returns
    -------
    LegacyVLLMConfig
        Legacy msgspec-based vLLM configuration struct with all fields
        populated from app_config.vllm, including converted run mode and
        embedding mode enums.
    """
    vllm = app_config.vllm
    run_mode = LegacyVLLMRunMode(mode=vllm.run_mode)
    embedding_mode = LegacyVLLMEmbeddingMode.from_value(vllm.embedding_mode)
    return LegacyVLLMConfig(
        base_url=vllm.base_url,
        model=vllm.model,
        batch_size=vllm.batch_size,
        embedding_dim=vllm.embedding_dim,
        timeout_s=vllm.timeout_s,
        run=run_mode,
        memory_utilization=vllm.memory_utilization,
        max_num_batched_tokens=vllm.max_num_batched_tokens,
        normalize=vllm.normalize,
        embedding_mode=embedding_mode,
        max_concurrent_requests=vllm.max_concurrent_requests,
        task=vllm.task,
    )


def _convert_bm25_config(app_config: AppConfig) -> LegacyBM25Config:
    """Convert AppConfig BM25 settings to legacy BM25Config format.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing BM25 settings to convert.

    Returns
    -------
    LegacyBM25Config
        Legacy msgspec-based BM25 configuration struct with all fields
        populated from app_config.bm25, including corpus directory, index
        directory, ranking parameters, RM3 settings, and analyzer configuration.
    """
    bm25 = app_config.bm25
    return LegacyBM25Config(
        corpus_json_dir=str(bm25.corpus_json_dir),
        index_dir=str(bm25.index_dir),
        threads=bm25.threads,
        enabled=bm25.enabled,
        k1=bm25.k1,
        b=bm25.b,
        rm3_enabled=bm25.rm3_enabled,
        rm3_fb_docs=bm25.rm3_fb_docs,
        rm3_fb_terms=bm25.rm3_fb_terms,
        rm3_original_query_weight=bm25.rm3_original_query_weight,
        analyzer=bm25.analyzer,
        stopwords=tuple(bm25.stopwords),
    )


def _convert_xtr_config(app_config: AppConfig) -> LegacyXTRConfig:
    """Convert AppConfig XTR settings to legacy XTRConfig format.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing XTR settings to convert.

    Returns
    -------
    LegacyXTRConfig
        Legacy msgspec-based XTR configuration struct populated from AppConfig.
    """
    xtr = app_config.xtr
    return LegacyXTRConfig(
        model_id=xtr.model_id,
        device=xtr.device,
        max_query_tokens=xtr.max_query_tokens,
        candidate_k=xtr.candidate_k,
        dim=xtr.dim,
        dtype=xtr.dtype,
        enable=xtr.enable,
        mode=xtr.mode,
    )


def settings_from_app_config(app_config: AppConfig, *, base: Settings | None = None) -> Settings:
    """Return msgspec Settings with AppConfig overrides applied.

    Parameters
    ----------
    app_config : AppConfig
        Immutable configuration produced by :func:`load_app_config`.
    base : Settings | None, optional
        Optional Settings instance to mutate. Defaults to :func:`load_settings()`.

    Returns
    -------
    Settings
        Settings struct whose path-related entries mirror AppConfig.
    """
    base_settings = base or load_settings()
    patched_paths = structs.replace(
        base_settings.paths,
        repo_root=str(app_config.paths.repo_root),
        data_dir=str(app_config.paths.data_dir),
        duckdb_path=str(app_config.duckdb.database),
        faiss_index=str(app_config.faiss.index_path),
    )
    splade_cfg = _convert_splade_config(app_config)
    bm25_cfg = _convert_bm25_config(app_config)
    embeddings_cfg = _convert_embeddings_config(app_config)
    vllm_cfg = _convert_vllm_config(app_config)
    xtr_cfg = _convert_xtr_config(app_config)
    index_cfg = app_config.index
    prf_cfg = LegacyPRFConfig(
        enable_auto=index_cfg.prf.enable_auto,
        fb_docs=index_cfg.prf.fb_docs,
        fb_terms=index_cfg.prf.fb_terms,
        orig_weight=index_cfg.prf.orig_weight,
        short_query_max_terms=index_cfg.prf.short_query_max_terms,
        symbol_like_regex=index_cfg.prf.symbol_like_regex,
        head_terms_csv=index_cfg.prf.head_terms_csv,
    )
    patched_index = structs.replace(
        base_settings.index,
        vec_dim=index_cfg.vec_dim,
        chunk_budget=index_cfg.chunk_budget,
        faiss_nlist=index_cfg.faiss_nlist,
        faiss_nprobe=index_cfg.faiss_nprobe,
        bm25_k1=index_cfg.bm25_k1,
        bm25_b=index_cfg.bm25_b,
        rrf_k=index_cfg.rrf_k,
        enable_bm25_channel=index_cfg.enable_bm25_channel,
        enable_splade_channel=index_cfg.enable_splade_channel,
        hybrid_top_k_per_channel=index_cfg.hybrid_top_k_per_channel,
        faiss_preload=index_cfg.faiss_preload,
        duckdb_materialize=index_cfg.duckdb_materialize,
        preview_max_chars=index_cfg.preview_max_chars,
        compaction_threshold=index_cfg.compaction_threshold,
        rrf_weights=dict(index_cfg.rrf_weights),
        hybrid_prefetch=dict(index_cfg.hybrid_prefetch),
        hybrid_use_rrf=index_cfg.hybrid_use_rrf,
        hybrid_weights_override=dict(index_cfg.hybrid_weights_override),
        prf=prf_cfg,
        recency_enabled=index_cfg.recency_enabled,
        recency_half_life_days=index_cfg.recency_half_life_days,
        recency_max_boost=index_cfg.recency_max_boost,
        recency_table=index_cfg.recency_table,
        faiss_family=index_cfg.faiss_family,
        nlist=index_cfg.nlist,
        pq_m=index_cfg.pq_m,
        pq_nbits=index_cfg.pq_nbits,
        opq_m=index_cfg.opq_m,
        hnsw_m=index_cfg.hnsw_m,
        hnsw_ef_construction=index_cfg.hnsw_ef_construction,
        default_k=index_cfg.default_k,
        default_nprobe=index_cfg.default_nprobe,
        hnsw_ef_search=index_cfg.hnsw_ef_search,
        refine_k_factor=index_cfg.refine_k_factor,
        autotune_on_start=index_cfg.autotune_on_start,
        enable_range_search=index_cfg.enable_range_search,
        semantic_min_score=index_cfg.semantic_min_score,
    )
    return structs.replace(
        base_settings,
        paths=patched_paths,
        bm25=bm25_cfg,
        splade=splade_cfg,
        embeddings=embeddings_cfg,
        vllm=vllm_cfg,
        xtr=xtr_cfg,
        index=patched_index,
    )


__all__ = ["settings_from_app_config"]
