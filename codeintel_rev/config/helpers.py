"""Narrow accessors for subsystem configuration."""

from __future__ import annotations

from typing import Final

from codeintel_rev.config.api import AppConfig, DuckDBSettings, FAISSSettings, SearchSettings

__all__: Final = [
    "duckdb_settings",
    "faiss_settings",
    "search_settings",
]


def faiss_settings(cfg: AppConfig) -> FAISSSettings:
    """Return FAISS settings from the supplied config.

    Returns
    -------
    FAISSSettings
        FAISS-specific configuration segment.
    """
    return cfg.faiss


def duckdb_settings(cfg: AppConfig) -> DuckDBSettings:
    """Return DuckDB settings from the supplied config.

    Returns
    -------
    DuckDBSettings
        DuckDB subsystem configuration.
    """
    return cfg.duckdb


def search_settings(cfg: AppConfig) -> SearchSettings:
    """Return hybrid search settings from the supplied config.

    Returns
    -------
    SearchSettings
        Hybrid retrieval weighting parameters.
    """
    return cfg.search
