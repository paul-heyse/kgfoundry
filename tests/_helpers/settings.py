"""Helpers for constructing AppConfig instances tailored for tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    BM25Settings,
    EmbeddingsSettings,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    SearchSettings,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)
from codeintel_rev.config.api import (
    DuckDBSettings as ApiDuckDBSettings,
)
from codeintel_rev.config.api import (
    PathsConfig as ApiPathsConfig,
)
from codeintel_rev.config.paths import ResolvedPaths

DEFAULT_XTR_SETTINGS = XTRSettings(
    model_id="nomic-ai/CodeRankEmbed",
    device="cuda",
    max_query_tokens=256,
    candidate_k=200,
    dim=768,
    dtype="float16",
    enable=False,
    mode="narrow",
)


def build_app_config_from_paths(paths: ResolvedPaths) -> AppConfig:
    """Produce a minimal AppConfig derived from resolved application paths.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved filesystem paths used to populate AppConfig.

    Returns
    -------
    AppConfig
        Application configuration whose path and DuckDB entries mirror ``paths``.
    """
    paths_cfg = ApiPathsConfig(
        repo_root=paths.repo_root,
        data_dir=paths.data_dir,
        cache_dir=paths.cache_dir,
        logs_dir=paths.logs_dir,
    )
    duck_cfg = ApiDuckDBSettings(database=paths.duckdb_path)
    faiss_cfg = FAISSSettings(index_path=paths.faiss_index)
    bm25_cfg = BM25Settings(
        corpus_json_dir=paths.data_dir / "bm25_json",
        index_dir=paths.lucene_dir / "bm25",
    )
    embeddings_cfg = EmbeddingsSettings()
    vllm_cfg = VLLMSettings()
    xtr_cfg = DEFAULT_XTR_SETTINGS
    index_cfg = IndexSettings()
    splade_cfg = SpladeSettings(
        model_id="naver/splade-v3",
        model_dir=paths.repo_root / "models" / "splade-v3",
        onnx_dir=paths.repo_root / "models" / "splade-v3" / "onnx",
        onnx_file="model_qint8.onnx",
        vectors_dir=paths.data_dir / "splade_vectors",
        index_dir=paths.repo_root / "indexes" / "splade_v3_impact",
        provider="CPUExecutionProvider",
        quantization=100,
        max_terms=3000,
        max_clause_count=4096,
        batch_size=32,
        threads=8,
        enabled=True,
        max_query_terms=64,
        prune_below=0.0,
        analyzer="wordpiece",
        static_prune_pct=0.0,
    )
    return AppConfig(
        version=CONFIG_API_VERSION,
        paths=paths_cfg,
        duckdb=duck_cfg,
        faiss=faiss_cfg,
        bm25=bm25_cfg,
        splade=splade_cfg,
        xtr=xtr_cfg,
        index=index_cfg,
        embeddings=embeddings_cfg,
        vllm=vllm_cfg,
        search=SearchSettings(),
        logging=LoggingSettings(),
    )


def build_app_config_for_repo(
    repo_root: Path,
    *,
    bm25_overrides: Mapping[str, Any] | None = None,
    splade_overrides: Mapping[str, Any] | None = None,
    index_overrides: Mapping[str, Any] | None = None,
) -> AppConfig:
    """Return AppConfig configured to point at ``repo_root``.

    Parameters
    ----------
    repo_root : Path
        Repository root directory for configuration paths.
    bm25_overrides : Mapping[str, Any] | None, optional
        Optional BM25 configuration overrides, by default None.
    splade_overrides : Mapping[str, Any] | None, optional
        Optional SPLADE configuration overrides, by default None.
    index_overrides : Mapping[str, Any] | None, optional
        Optional index configuration overrides, by default None.

    Returns
    -------
    AppConfig
        Application configuration with paths and settings configured for the
        specified repository root.
    """
    repo_root = repo_root.resolve()
    data_dir = repo_root / "data"
    paths_cfg = ApiPathsConfig(
        repo_root=repo_root,
        data_dir=data_dir,
        cache_dir=repo_root / ".cache",
        logs_dir=repo_root / "logs",
    )
    duck_cfg = ApiDuckDBSettings(database=data_dir / "catalog.duckdb")
    faiss_cfg = FAISSSettings(index_path=data_dir / "faiss" / "code.ivfpq.faiss")
    bm25_cfg = BM25Settings(
        corpus_json_dir=data_dir / "bm25_json",
        index_dir=repo_root / "indexes" / "bm25",
    )
    if bm25_overrides:
        bm25_cfg = dc_replace(bm25_cfg, **bm25_overrides)
    splade_cfg = SpladeSettings(
        model_id="naver/splade-v3",
        model_dir=repo_root / "models" / "splade-v3",
        onnx_dir=repo_root / "models" / "splade-v3" / "onnx",
        onnx_file="model_qint8.onnx",
        vectors_dir=data_dir / "splade_vectors",
        index_dir=repo_root / "indexes" / "splade_v3_impact",
        provider="CPUExecutionProvider",
        quantization=100,
        max_terms=3000,
        max_clause_count=4096,
        batch_size=32,
        threads=8,
        enabled=True,
        max_query_terms=64,
        prune_below=0.0,
        analyzer="wordpiece",
        static_prune_pct=0.0,
    )
    if splade_overrides:
        splade_cfg = dc_replace(splade_cfg, **splade_overrides)
    index_cfg = IndexSettings()
    if index_overrides:
        index_cfg = dc_replace(index_cfg, **index_overrides)
    return AppConfig(
        version=CONFIG_API_VERSION,
        paths=paths_cfg,
        duckdb=duck_cfg,
        faiss=faiss_cfg,
        bm25=bm25_cfg,
        splade=splade_cfg,
        xtr=DEFAULT_XTR_SETTINGS,
        index=index_cfg,
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
    )


def scaffold_repo_root(repo_root: Path) -> None:
    """Create the minimum filesystem layout expected by readiness checks.

    Parameters
    ----------
    repo_root : Path
        Root directory path to scaffold.
    """
    repo_root.mkdir(parents=True, exist_ok=True)
    for relative in (
        "config",
        "data",
        "data/vectors",
        "logs",
        ".cache",
        ".tmp",
        "plugins",
    ):
        (repo_root / relative).mkdir(parents=True, exist_ok=True)
    config_file = repo_root / "config" / "app.yml"
    if not config_file.exists():
        config_file.write_text("tests: true", encoding="utf-8")


__all__ = [
    "DEFAULT_XTR_SETTINGS",
    "build_app_config_for_repo",
    "build_app_config_from_paths",
    "scaffold_repo_root",
]
