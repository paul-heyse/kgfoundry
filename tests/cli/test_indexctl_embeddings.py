"""Tests for `indexctl embeddings` commands."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import duckdb
import numpy as np
import pyarrow.parquet as pq
import pytest
from codeintel_rev.cli import indexctl as indexctl_module
from codeintel_rev.cli.indexctl import IndexctlCliContext
from codeintel_rev.cli.indexctl import app as indexctl_app
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
from codeintel_rev.config.settings import Settings
from codeintel_rev.embeddings import EmbeddingProvider
from codeintel_rev.embeddings.embedding_service import EmbeddingMetadata

from tests._helpers import assertions, cli, constants
from tests._helpers.settings import build_settings_for_repo


class _StubProvider:
    """Deterministic embedding provider used by the CLI tests."""

    def __init__(self) -> None:
        self.metadata = EmbeddingMetadata(
            provider="stub",
            model_name="stub-model",
            dimension=2,
            dtype="float32",
            normalize=True,
            device="cpu",
        )

    @staticmethod
    def fingerprint() -> str:
        return "stub-fingerprint"

    @staticmethod
    def embed_texts(texts: list[str]) -> np.ndarray:
        return np.vstack([np.arange(2, dtype=np.float32) + idx for idx in range(len(texts))])

    def close(self) -> None:
        """No-op."""


@pytest.fixture(name="indexctl_context")
def _indexctl_context() -> IndexctlCliContext:
    """Provide an indexctl CLI context with deterministic embedding provider.

    Returns
    -------
    IndexctlCliContext
        Context configured with a deterministic embedding provider stub.
    """
    base = IndexctlCliContext.production()

    def _provider_factory(_settings: Settings) -> EmbeddingProvider:
        return cast("EmbeddingProvider", _StubProvider())

    return replace(base, embedding_provider_factory=_provider_factory)


def _create_duckdb(path: Path) -> None:
    conn = duckdb.connect(str(path))
    conn.execute(
        """
        CREATE TABLE chunks (
            id INTEGER,
            uri VARCHAR,
            start_byte INTEGER,
            end_byte INTEGER,
            start_line INTEGER,
            end_line INTEGER,
            content VARCHAR,
            lang VARCHAR,
            symbols VARCHAR[],
            content_hash BIGINT
        )
        """,
    )
    rows = [
        (0, "src/app.py", 0, 10, 0, 0, "first chunk", "python", ["sym"], 123),
        (1, "src/app.py", 11, 20, 1, 1, "second chunk", "python", ["sym"], 456),
    ]
    conn.executemany(
        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.close()


def test_embeddings_build_writes_parquet_and_manifest(
    tmp_path: Path,
    indexctl_context: IndexctlCliContext,
) -> None:
    """`indexctl embeddings build` writes artifacts and manifest metadata."""
    db_path = tmp_path / "catalog.duckdb"
    _create_duckdb(db_path)
    output = tmp_path / "embeddings.parquet"

    result = cli.invoke(
        indexctl_app,
        [
            "embeddings",
            "build",
            "--duckdb",
            str(db_path),
            "--output",
            str(output),
            "--chunk-size",
            "1",
            "--force",
        ],
        catch_exceptions=False,
        obj={"cli_context": indexctl_context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.output)

    manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assertions.expect_equal(manifest["vectors"], constants.BATCH_SIZES.minimal)
    assertions.expect_equal(manifest["provider"], "stub")

    table = pq.read_table(output)
    assertions.expect_equal(table.num_rows, constants.BATCH_SIZES.minimal)


def test_embeddings_validate_passes_with_stub(
    tmp_path: Path,
    indexctl_context: IndexctlCliContext,
) -> None:
    """`indexctl embeddings validate` succeeds with the stub provider."""
    db_path = tmp_path / "catalog.duckdb"
    _create_duckdb(db_path)
    output = tmp_path / "embeddings.parquet"
    build_result = cli.invoke(
        indexctl_app,
        [
            "embeddings",
            "build",
            "--duckdb",
            str(db_path),
            "--output",
            str(output),
            "--chunk-size",
            "1",
            "--force",
        ],
        catch_exceptions=False,
        obj={"cli_context": indexctl_context},
    )
    assertions.expect_equal(build_result.exit_code, 0, reason=build_result.output)

    validate_result = cli.invoke(
        indexctl_app,
        [
            "embeddings",
            "validate",
            "--parquet",
            str(output),
            "--samples",
            str(constants.BATCH_SIZES.minimal),
        ],
        catch_exceptions=False,
        obj={"cli_context": indexctl_context},
    )
    assertions.expect_equal(validate_result.exit_code, 0, reason=validate_result.output)


def _app_config_with_duckdb(repo_root: Path, duckdb_path: Path) -> AppConfig:
    """Return minimal AppConfig whose DuckDB path points at ``duckdb_path``.

    Returns
    -------
    AppConfig
        Configuration object with deterministic paths for testing helpers.
    """
    data_dir = repo_root / "data"
    paths_cfg = ApiPathsConfig(
        repo_root=repo_root,
        data_dir=data_dir,
        cache_dir=repo_root / ".cache",
        logs_dir=repo_root / "logs",
    )
    return AppConfig(
        version=CONFIG_API_VERSION,
        paths=paths_cfg,
        duckdb=ApiDuckDBSettings(database=duckdb_path),
        faiss=FAISSSettings(index_path=repo_root / "faiss.index"),
        search=SearchSettings(),
        logging=LoggingSettings(),
    )


def test_resolve_duck_path_prefers_app_config_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default DuckDB catalog path honors AppConfig when no override is provided."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    duck_path = repo_root / "custom.duckdb"
    duck_path.touch()
    app_config = _app_config_with_duckdb(repo_root, duck_path)
    settings = build_settings_for_repo(repo_root)
    monkeypatch.setattr(indexctl_module, "_cached_app_config", lambda: app_config)
    resolved = indexctl_module.resolve_duck_path(settings, version_dir=None, override=None)
    assertions.expect_equal(resolved, duck_path.resolve())
