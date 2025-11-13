"""Tests for `indexctl embeddings` commands."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.append(str((Path(__file__).resolve().parents[2] / "src")))

import duckdb
import numpy as np
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner


class _NoopMetric:
    def labels(self, **_kwargs: object) -> _NoopMetric:
        return self

    def observe(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
        return None

    def inc(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
        return None

    def set(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
        return None


def _install_observability_stubs() -> None:
    import contextlib

    metric_mod = types.ModuleType("codeintel_rev.observability.metrics")

    def _build_metric(*_args: object, **_kwargs: object) -> _NoopMetric:
        return _NoopMetric()

    metric_mod.build_counter = _build_metric  # type: ignore[attr-defined]
    metric_mod.build_histogram = _build_metric  # type: ignore[attr-defined]
    metric_mod.build_gauge = _build_metric  # type: ignore[attr-defined]
    sys.modules.setdefault("codeintel_rev.observability.metrics", metric_mod)

    timeline_mod = types.ModuleType("codeintel_rev.observability.timeline")

    class _Timeline:
        def event(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
            return None

    timeline_mod.Timeline = _Timeline  # type: ignore[attr-defined]
    timeline_mod.current_timeline = lambda: None  # type: ignore[attr-defined]
    sys.modules.setdefault("codeintel_rev.observability.timeline", timeline_mod)

    sys.modules.setdefault(
        "codeintel_rev.observability", types.ModuleType("codeintel_rev.observability")
    )

    otel_mod = types.ModuleType("codeintel_rev.observability.otel")

    def _as_span(*_args: object, **_kwargs: object):
        return contextlib.nullcontext()

    otel_mod.as_span = _as_span  # type: ignore[attr-defined]
    sys.modules.setdefault("codeintel_rev.observability.otel", otel_mod)
    sys.modules.setdefault(
        "codeintel_rev.observability.runtime_observer",
        types.ModuleType("codeintel_rev.observability.runtime_observer"),
    )

    decorators_mod = types.ModuleType("codeintel_rev.telemetry.decorators")

    def _span_context(*_args: object, **_kwargs: object):
        return contextlib.nullcontext()

    decorators_mod.span_context = _span_context  # type: ignore[attr-defined]
    sys.modules.setdefault("codeintel_rev.telemetry.decorators", decorators_mod)

    sys.modules.setdefault("codeintel_rev.telemetry", types.ModuleType("codeintel_rev.telemetry"))
    sys.modules.setdefault(
        "codeintel_rev.telemetry.logging", types.ModuleType("codeintel_rev.telemetry.logging")
    )
    reporter_mod = types.ModuleType("codeintel_rev.telemetry.reporter")
    reporter_mod.emit_checkpoint = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    sys.modules.setdefault("codeintel_rev.telemetry.reporter", reporter_mod)


_install_observability_stubs()

from codeintel_rev.cli.indexctl import app as indexctl_app
from codeintel_rev.embeddings.embedding_service import EmbeddingMetadata


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

    def fingerprint(self) -> str:
        return "stub-fingerprint"

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.vstack([np.arange(2, dtype=np.float32) + idx for idx in range(len(texts))])

    def close(self) -> None:
        """No-op."""


@pytest.fixture()
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "codeintel_rev.cli.indexctl.get_embedding_provider",
        lambda settings: _StubProvider(),
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


def test_embeddings_build_writes_parquet_and_manifest(tmp_path: Path, stub_provider: None) -> None:
    db_path = tmp_path / "catalog.duckdb"
    _create_duckdb(db_path)
    output = tmp_path / "embeddings.parquet"

    runner = CliRunner()
    result = runner.invoke(
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
    )
    assert result.exit_code == 0, result.output

    manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["vectors"] == 2
    assert manifest["provider"] == "stub"

    table = pq.read_table(output)
    assert table.num_rows == 2


def test_embeddings_validate_passes_with_stub(tmp_path: Path, stub_provider: None) -> None:
    db_path = tmp_path / "catalog.duckdb"
    _create_duckdb(db_path)
    output = tmp_path / "embeddings.parquet"
    runner = CliRunner()
    build_result = runner.invoke(
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
    )
    assert build_result.exit_code == 0

    validate_result = runner.invoke(
        indexctl_app,
        ["embeddings", "validate", "--parquet", str(output), "--samples", "2"],
    )
    assert validate_result.exit_code == 0, validate_result.output
