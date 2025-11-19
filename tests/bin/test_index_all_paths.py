"""Tests for index_all path resolution helpers."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.bin import index_all
from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    FAISSSettings,
    LoggingSettings,
    SearchSettings,
)
from codeintel_rev.config.api import (
    DuckDBSettings as ApiDuckDBSettings,
)
from codeintel_rev.config.api import (
    PathsConfig as ApiPathsConfig,
)

from tests._helpers import assertions
from tests._helpers.settings import build_settings_for_repo


def test_resolve_paths_prefers_app_config_overrides(tmp_path: Path) -> None:
    """resolve_pipeline_paths should honor AppConfig overrides for FAISS and DuckDB."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings = build_settings_for_repo(repo_root)
    duckdb_override = repo_root / "custom.duckdb"
    faiss_override = repo_root / "custom.faiss"
    app_config = AppConfig(
        version=CONFIG_API_VERSION,
        paths=ApiPathsConfig(
            repo_root=repo_root,
            data_dir=repo_root / "data",
            cache_dir=repo_root / ".cache",
            logs_dir=repo_root / "logs",
        ),
        duckdb=ApiDuckDBSettings(database=duckdb_override),
        faiss=FAISSSettings(index_path=faiss_override),
        search=SearchSettings(),
        logging=LoggingSettings(),
    )

    resolved = index_all.resolve_pipeline_paths(settings, app_config)

    assertions.expect_equal(resolved.duckdb_path, duckdb_override)
    assertions.expect_equal(resolved.faiss_index, faiss_override)
