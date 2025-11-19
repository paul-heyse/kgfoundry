"""Configuration API for codeintel_rev."""

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    SpladeSettings,
    validate_config,
)
from codeintel_rev.config.helpers import (
    bm25_settings,
    duckdb_settings,
    faiss_settings,
    search_settings,
    splade_settings,
)
from codeintel_rev.config.loader import load_app_config

__all__ = [
    "CONFIG_API_VERSION",
    "AppConfig",
    "BM25Settings",
    "DuckDBSettings",
    "FAISSSettings",
    "LoggingSettings",
    "PathsConfig",
    "SearchSettings",
    "SpladeSettings",
    "bm25_settings",
    "duckdb_settings",
    "faiss_settings",
    "load_app_config",
    "search_settings",
    "splade_settings",
    "validate_config",
]
