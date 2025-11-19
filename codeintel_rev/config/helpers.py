"""Narrow accessors for subsystem configuration."""

from __future__ import annotations

from typing import Final

from codeintel_rev.config.api import (
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    EmbeddingsSettings,
    FAISSSettings,
    IndexSettings,
    SearchSettings,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)

__all__: Final = [
    "bm25_settings",
    "duckdb_settings",
    "embeddings_settings",
    "faiss_settings",
    "index_settings",
    "search_settings",
    "splade_settings",
    "vllm_settings",
    "xtr_settings",
]


def faiss_settings(cfg: AppConfig) -> FAISSSettings:
    """Return FAISS settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    FAISSSettings
        FAISS-specific configuration segment.
    """
    return cfg.faiss


def duckdb_settings(cfg: AppConfig) -> DuckDBSettings:
    """Return DuckDB settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    DuckDBSettings
        DuckDB subsystem configuration.
    """
    return cfg.duckdb


def search_settings(cfg: AppConfig) -> SearchSettings:
    """Return hybrid search settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    SearchSettings
        Hybrid retrieval weighting parameters.
    """
    return cfg.search


def splade_settings(cfg: AppConfig) -> SpladeSettings:
    """Return SPLADE settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    SpladeSettings
        SPLADE-specific configuration block.
    """
    return cfg.splade


def bm25_settings(cfg: AppConfig) -> BM25Settings:
    """Return BM25 settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    BM25Settings
        BM25-specific configuration segment.
    """
    return cfg.bm25


def embeddings_settings(cfg: AppConfig) -> EmbeddingsSettings:
    """Return embedding provider settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    EmbeddingsSettings
        Embedding provider configuration segment.
    """
    return cfg.embeddings


def vllm_settings(cfg: AppConfig) -> VLLMSettings:
    """Return vLLM settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    VLLMSettings
        vLLM-specific configuration segment.
    """
    return cfg.vllm


def xtr_settings(cfg: AppConfig) -> XTRSettings:
    """Return XTR settings from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    XTRSettings
        XTR-specific configuration segment.
    """
    return cfg.xtr


def index_settings(cfg: AppConfig) -> IndexSettings:
    """Return index configuration from the supplied config.

    Parameters
    ----------
    cfg : AppConfig
        Application configuration object.

    Returns
    -------
    IndexSettings
        Index configuration settings segment.
    """
    return cfg.index
