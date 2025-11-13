"""Tests for `indexctl embeddings` commands."""

from __future__ import annotations

import functools
import json
import sys
import types
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any, cast

import duckdb
import numpy as np
import pyarrow.parquet as pq
import pytest
from typer import Typer
from typer.testing import CliRunner

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from codeintel_rev.embeddings.embedding_service import EmbeddingMetadata


def _install_metric_stubs() -> None:
    metric_mod = types.ModuleType("codeintel_rev.observability.metrics")

    class _NoopMetric:
        def labels(self, **_kwargs: object) -> _NoopMetric:
            return self

        def observe(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
            return None

        def inc(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
            return None

        def set(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
            return None

    def _build_metric(*_args: object, **_kwargs: object) -> _NoopMetric:
        return _NoopMetric()

    metrics_stub = cast("Any", metric_mod)
    metrics_stub.build_counter = _build_metric
    metrics_stub.build_histogram = _build_metric
    metrics_stub.build_gauge = _build_metric
    sys.modules.setdefault("codeintel_rev.observability.metrics", metric_mod)


def _install_timeline_stubs() -> None:
    timeline_mod = types.ModuleType("codeintel_rev.observability.timeline")

    class _Timeline:
        def __init__(
            self,
            session_id: str = "test",
            run_id: str = "test",
            *,
            sampled: bool = True,
        ) -> None:
            self.session_id = session_id
            self.run_id = run_id
            self.sampled = sampled
            self.metadata: dict[str, object] = {}

        def event(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
            return None

        def operation(self, *_args: object, **_kwargs: object) -> AbstractContextManager[None]:
            return nullcontext()

        def step(self, *_args: object, **_kwargs: object) -> AbstractContextManager[None]:
            return nullcontext()

        def set_metadata(self, **attrs: object) -> None:
            self.metadata.update(attrs)

        def snapshot(self) -> list[dict[str, object]]:
            return []

    timeline_stub = cast("Any", timeline_mod)
    timeline_stub.Timeline = _Timeline
    timeline_stub.current_timeline = lambda: None
    timeline_stub.new_timeline = lambda *_args, **_kwargs: _Timeline()
    timeline_stub.bind_timeline = lambda *_args, **_kwargs: nullcontext()
    sys.modules.setdefault("codeintel_rev.observability.timeline", timeline_mod)

    sys.modules.setdefault(
        "codeintel_rev.observability", types.ModuleType("codeintel_rev.observability")
    )


def _install_telemetry_stubs() -> None:
    otel_mod = types.ModuleType("codeintel_rev.observability.otel")

    def _as_span(*_args: object, **_kwargs: object) -> AbstractContextManager[None]:
        return nullcontext()

    cast("Any", otel_mod).as_span = _as_span
    sys.modules.setdefault("codeintel_rev.observability.otel", otel_mod)
    sys.modules.setdefault(
        "codeintel_rev.observability.runtime_observer",
        types.ModuleType("codeintel_rev.observability.runtime_observer"),
    )

    decorators_mod = types.ModuleType("codeintel_rev.telemetry.decorators")

    def _span_context(*_args: object, **_kwargs: object) -> AbstractContextManager[None]:
        return nullcontext()

    cast("Any", decorators_mod).span_context = _span_context
    sys.modules.setdefault("codeintel_rev.telemetry.decorators", decorators_mod)

    sys.modules.setdefault("codeintel_rev.telemetry", types.ModuleType("codeintel_rev.telemetry"))
    sys.modules.setdefault(
        "codeintel_rev.telemetry.logging", types.ModuleType("codeintel_rev.telemetry.logging")
    )


def _install_reporting_stubs() -> None:
    reporter_mod = types.ModuleType("codeintel_rev.telemetry.reporter")

    def _noop_emit_checkpoint(*_: object, **__: object) -> None:
        return None

    reporter_stub = cast("Any", reporter_mod)
    reporter_stub.emit_checkpoint = _noop_emit_checkpoint
    reporter_stub.start_run = _noop_emit_checkpoint
    reporter_stub.finalize_run = _noop_emit_checkpoint
    sys.modules.setdefault("codeintel_rev.telemetry.reporter", reporter_mod)

    reporting_mod = types.ModuleType("codeintel_rev.observability.reporting")
    reporting_stub = cast("Any", reporting_mod)
    reporting_stub.render_run_report = _noop_emit_checkpoint
    reporting_stub.latest_run_report = lambda: None
    reporting_stub.build_timeline_run_report = _noop_emit_checkpoint
    sys.modules.setdefault("codeintel_rev.observability.reporting", reporting_mod)


def _install_observability_stubs() -> None:
    _install_metric_stubs()
    _install_timeline_stubs()
    _install_telemetry_stubs()
    _install_reporting_stubs()


@functools.lru_cache(maxsize=1)
def _load_cli_app() -> Typer:
    _install_observability_stubs()
    from codeintel_rev.cli.indexctl import app as loaded_app

    return loaded_app


indexctl_app = _load_cli_app()


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


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.usefixtures("stub_provider")
def test_embeddings_validate_passes_with_stub(tmp_path: Path) -> None:
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
