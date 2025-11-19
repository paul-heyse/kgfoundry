"""Compatibility helpers for bridging AppConfig to legacy Settings structs."""

from __future__ import annotations

from msgspec import structs

from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.settings import (
    Settings,
    SpladeConfig as LegacySpladeConfig,
    SpladeOnnxQueryConfig as LegacySpladeOnnxQueryConfig,
    load_settings,
)


def _convert_splade_config(app_config: AppConfig) -> LegacySpladeConfig:
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
    patched_index = structs.replace(
        base_settings.index,
        enable_splade_channel=app_config.splade.enabled,
    )
    return structs.replace(base_settings, paths=patched_paths, splade=splade_cfg, index=patched_index)


__all__ = ["settings_from_app_config"]
