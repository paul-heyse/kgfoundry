"""CLI tests for SPLADE maintenance commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from click.testing import Result
from codeintel_rev.cli import app as root_app
from codeintel_rev.cli.splade import SpladeCliContext
from codeintel_rev.io.splade_manager import (
    SpladeArtifactsManager,
    SpladeBenchmarkOptions,
    SpladeBenchmarkSummary,
    SpladeBuildOptions,
    SpladeEncodeOptions,
    SpladeEncoderService,
    SpladeEncodingSummary,
    SpladeExportOptions,
    SpladeExportSummary,
    SpladeIndexManager,
    SpladeIndexMetadata,
)
from typer.testing import CliRunner

from tests._helpers import assertions

runner = CliRunner()


class _StubArtifactsManager:
    """Stub artifacts manager recording export invocations."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[SpladeExportOptions] = []

    def export_onnx(self, options: SpladeExportOptions | None = None) -> SpladeExportSummary:
        """Export ONNX artifact and record call.

        Parameters
        ----------
        options : SpladeExportOptions | None, optional
            Export options to record.

        Returns
        -------
        SpladeExportSummary
            Stub export summary with paths.
        """
        opts = options or SpladeExportOptions()
        self.calls.append(opts)
        onnx_dir = self.tmp_path / "models" / "splade-v3" / "onnx"
        onnx_dir.mkdir(parents=True, exist_ok=True)
        onnx_file = onnx_dir / (opts.file_name or "model_qint8.onnx")
        onnx_file.write_text("stub", encoding="utf-8")
        metadata_path = onnx_dir / "artifacts.json"
        metadata_path.write_text(json.dumps({"onnx_file": str(onnx_file)}), encoding="utf-8")
        return SpladeExportSummary(
            onnx_file=str(onnx_file),
            metadata_path=str(metadata_path),
        )


class _StubEncoderService:
    """Stub encoding service for CLI verification."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[tuple[Path, SpladeEncodeOptions | None]] = []
        self.benchmark_calls: list[tuple[list[str], SpladeBenchmarkOptions]] = []

    def encode_corpus(
        self,
        source: Path,
        options: SpladeEncodeOptions | None = None,
    ) -> SpladeEncodingSummary:
        """Encode corpus and record call.

        Parameters
        ----------
        source : Path
            Source corpus path to record.
        options : SpladeEncodeOptions | None, optional
            Encode options to record.

        Returns
        -------
        SpladeEncodingSummary
            Stub encoding summary with metadata paths.
        """
        self.calls.append((source, options))
        opts = options or SpladeEncodeOptions()
        target_dir = (
            Path(opts.output_dir) if opts.output_dir is not None else self.tmp_path / "vectors"
        )
        vectors_dir = target_dir.resolve()
        vectors_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = vectors_dir / "vectors_metadata.json"
        metadata_path.write_text(json.dumps({"doc_count": 3}), encoding="utf-8")
        return SpladeEncodingSummary(
            doc_count=3,
            vectors_dir=str(vectors_dir),
            metadata_path=str(metadata_path),
            shard_count=1,
        )

    def benchmark_queries(
        self,
        queries: list[str],
        options: SpladeBenchmarkOptions | None = None,
    ) -> SpladeBenchmarkSummary:
        """Benchmark queries and record call.

        Parameters
        ----------
        queries : list[str]
            Query strings to benchmark.
        options : SpladeBenchmarkOptions | None, optional
            Benchmark options to record.

        Returns
        -------
        SpladeBenchmarkSummary
            Stub benchmark summary with latency metrics.
        """
        opts = options or SpladeBenchmarkOptions()
        self.benchmark_calls.append((list(queries), opts))
        return SpladeBenchmarkSummary(
            query_count=len(queries),
            warmup_iterations=opts.warmup_iterations,
            measure_iterations=opts.measure_iterations,
            min_latency_ms=5.0,
            max_latency_ms=7.5,
            mean_latency_ms=6.0,
            p50_latency_ms=6.0,
            p95_latency_ms=7.0,
            p99_latency_ms=7.5,
            provider=opts.provider or "CPUExecutionProvider",
            onnx_file="onnx/model_qint8.onnx",
        )


class _StubIndexManager:
    """Stub impact index manager for CLI tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[SpladeBuildOptions | None] = []

    def build_index(self, options: SpladeBuildOptions | None = None) -> SpladeIndexMetadata:
        """Build index and record call.

        Parameters
        ----------
        options : SpladeBuildOptions | None, optional
            Build options to record.

        Returns
        -------
        SpladeIndexMetadata
            Stub index metadata with test values.
        """
        self.calls.append(options)
        index_dir = (self.tmp_path / "indexes" / "splade").resolve()
        index_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = index_dir / "metadata.json"
        metadata_path.write_text(json.dumps({"doc_count": 5}), encoding="utf-8")
        vectors_dir = self.tmp_path / "vectors"
        vectors_dir.mkdir(parents=True, exist_ok=True)
        return SpladeIndexMetadata(
            doc_count=5,
            built_at="2025-01-01T00:00:00Z",
            vectors_dir=str(vectors_dir),
            corpus_digest="digest456",
            pyserini_version="stub",
            threads=options.threads if options and options.threads is not None else 8,
            index_dir=str(index_dir),
            index_size_bytes=512,
            generator="test",
        )


def _invoke_splade(
    args: list[str],
    *,
    context: SpladeCliContext,
    envelope_dir: Path,
) -> Result:
    return runner.invoke(
        root_app,
        [
            "splade",
            *args,
        ],
        obj={
            "splade_cli_context": context,
            "cli_run_overrides": {"envelope_dir": envelope_dir},
        },
    )


def test_export_onnx_cli(
    tmp_path: Path,
    splade_cli_context_builder: Callable[..., SpladeCliContext],
) -> None:
    """export-onnx should drive the artifacts manager and emit metadata."""
    stub = _StubArtifactsManager(tmp_path)
    context = splade_cli_context_builder(
        artifacts_factory=lambda: cast("SpladeArtifactsManager", stub)
    )

    result = _invoke_splade(
        [
            "export-onnx",
            "--model-id",
            "naver/splade-v3",
            "--quantization-config",
            "avx512",
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Exported ONNX artifact", result.stdout)
    assertions.expect_true(bool(stub.calls), reason="Expected export_onnx to be invoked")
    call = stub.calls[0]
    assertions.expect_equal(call.model_id, "naver/splade-v3")
    assertions.expect_equal(call.quantization_config, "avx512")


def test_encode_cli(
    tmp_path: Path,
    splade_cli_context_builder: Callable[..., SpladeCliContext],
) -> None:
    """Encode should invoke the encoder service and persist metadata artifacts."""
    stub = _StubEncoderService(tmp_path)
    context = splade_cli_context_builder(encoder_factory=lambda: cast("SpladeEncoderService", stub))

    source = tmp_path / "corpus.jsonl"
    source.write_text('{"id": "doc1", "contents": "text"}\n', encoding="utf-8")

    result = _invoke_splade(
        [
            "encode",
            str(source),
            "--batch-size",
            "16",
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Encoded corpus", result.stdout)
    assertions.expect_true(bool(stub.calls), reason="Expected encode_corpus to be invoked")
    _, options = stub.calls[0]
    assertions.expect_true(options is not None, reason="options should not be None")
    if options is None:  # pragma: no cover - defensive
        pytest.fail("options should not be None")
    assertions.expect_equal(options.batch_size, 16)
    metadata_path = stub.tmp_path / "vectors" / "vectors_metadata.json"
    assertions.expect_true(metadata_path.exists(), reason="metadata_path should exist")


def test_build_index_cli(
    tmp_path: Path,
    splade_cli_context_builder: Callable[..., SpladeCliContext],
) -> None:
    """build-index should dispatch to the index manager with parsed options."""
    stub = _StubIndexManager(tmp_path)
    context = splade_cli_context_builder(index_factory=lambda: cast("SpladeIndexManager", stub))

    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    result = _invoke_splade(
        [
            "build-index",
            "--vectors-dir",
            str(vectors_dir),
            "--threads",
            "12",
            "--max-clause-count",
            "8192",
            "--no-overwrite",
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Built impact index", result.stdout)
    assertions.expect_true(bool(stub.calls), reason="Expected build_index to be invoked")
    options = stub.calls[0]
    assertions.expect_true(
        isinstance(options, SpladeBuildOptions), reason="options should be SpladeBuildOptions"
    )
    if not isinstance(options, SpladeBuildOptions):  # pragma: no cover - defensive
        pytest.fail("options should be SpladeBuildOptions")
    assertions.expect_equal(options.vectors_dir, vectors_dir)
    assertions.expect_equal(options.threads, 12)
    assertions.expect_equal(options.max_clause_count, 8192)
    assertions.expect_false(options.overwrite, reason="overwrite should be False")


def test_bench_cli(
    tmp_path: Path,
    splade_cli_context_builder: Callable[..., SpladeCliContext],
) -> None:
    """Bench should invoke the encoder service benchmark workflow."""
    stub = _StubEncoderService(tmp_path)
    context = splade_cli_context_builder(encoder_factory=lambda: cast("SpladeEncoderService", stub))

    result = _invoke_splade(
        [
            "bench",
            "--query",
            "solar incentives",
            "--runs",
            "5",
            "--warmup",
            "2",
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Benchmark latency", result.stdout)
    assertions.expect_true(
        bool(stub.benchmark_calls), reason="Expected benchmark_queries to be invoked"
    )
    queries, options = stub.benchmark_calls[0]
    assertions.expect_sequence_equal(queries, ["solar incentives"])
    assertions.expect_equal(options.measure_iterations, 5)
    assertions.expect_equal(options.warmup_iterations, 2)
    assertions.expect_equal(options.provider, None)
    assertions.expect_equal(options.onnx_file, None)
