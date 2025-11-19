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
    patched_index = structs.replace(
        base_settings.index,
        enable_bm25_channel=app_config.bm25.enabled,
        bm25_k1=app_config.bm25.k1,
        bm25_b=app_config.bm25.b,
        enable_splade_channel=app_config.splade.enabled,
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
