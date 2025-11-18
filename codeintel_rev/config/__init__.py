"""Configuration API for codeintel_rev."""

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    validate_config,
)
from codeintel_rev.config.helpers import duckdb_settings, faiss_settings, search_settings
from codeintel_rev.config.loader import load_app_config

__all__ = [
    "CONFIG_API_VERSION",
    "AppConfig",
    "DuckDBSettings",
    "FAISSSettings",
    "LoggingSettings",
    "PathsConfig",
    "SearchSettings",
    "duckdb_settings",
    "faiss_settings",
    "load_app_config",
    "search_settings",
    "validate_config",
]
