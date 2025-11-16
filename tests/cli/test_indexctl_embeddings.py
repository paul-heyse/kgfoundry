"""Tests for `indexctl embeddings` commands."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.parquet as pq
import pytest
from codeintel_rev.cli.indexctl import app as indexctl_app
from codeintel_rev.embeddings.embedding_service import EmbeddingMetadata

from tests._helpers import assertions, cli, constants


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


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the deterministic stub provider for the duration of a test."""

    def _provider_factory(_settings: object) -> _StubProvider:
        return _StubProvider()

    monkeypatch.setattr(
        "codeintel_rev.cli.indexctl.get_embedding_provider",
        _provider_factory,
    )


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


@pytest.mark.usefixtures("stub_provider")
def test_embeddings_build_writes_parquet_and_manifest(tmp_path: Path) -> None:
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
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.output)

    manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assertions.expect_equal(manifest["vectors"], constants.BATCH_SIZES.minimal)
    assertions.expect_equal(manifest["provider"], "stub")

    table = pq.read_table(output)
    assertions.expect_equal(table.num_rows, constants.BATCH_SIZES.minimal)


@pytest.mark.usefixtures("stub_provider")
def test_embeddings_validate_passes_with_stub(tmp_path: Path) -> None:
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
    )
    assertions.expect_equal(validate_result.exit_code, 0, reason=validate_result.output)
