"""CLI tests for SPLADE maintenance commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from codeintel_rev.cli import app as root_app
from codeintel_rev.cli import splade as splade_cli
from codeintel_rev.io.splade_manager import (
    SpladeBuildOptions,
    SpladeEncodeOptions,
    SpladeEncodingSummary,
    SpladeExportOptions,
    SpladeExportSummary,
    SpladeIndexMetadata,
)
from tools import Paths
from typer.testing import CliRunner

runner = CliRunner()


class _StubArtifactsManager:
    """Stub artifacts manager recording export invocations."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[SpladeExportOptions] = []

    def export_onnx(self, options: SpladeExportOptions | None = None) -> SpladeExportSummary:
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

    def encode_corpus(
        self,
        source: Path,
        options: SpladeEncodeOptions | None = None,
    ) -> SpladeEncodingSummary:
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


class _StubIndexManager:
    """Stub impact index manager for CLI tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[SpladeBuildOptions | None] = []

    def build_index(self, options: SpladeBuildOptions | None = None) -> SpladeIndexMetadata:
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


def _patch_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect CLI envelope output artifacts to a temporary directory."""
    Paths.discover.cache_clear()

    def fake_discover(_start: Path | None = None) -> Paths:
        return Paths(
            repo_root=tmp_path,
            docs_data=tmp_path / "docs",
            cli_out_root=tmp_path / "cli",
        )

    monkeypatch.setattr(Paths, "discover", staticmethod(fake_discover))


def test_export_onnx_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """export-onnx should drive the artifacts manager and emit metadata."""
    stub = _StubArtifactsManager(tmp_path)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(splade_cli, "_create_artifacts_manager", lambda: stub)

    result = runner.invoke(
        root_app,
        [
            "splade",
            "export-onnx",
            "--model-id",
            "naver/splade-v3",
            "--quantization-config",
            "avx512",
        ],
    )

    assert result.exit_code == 0
    assert "Exported ONNX artifact" in result.stdout
    assert stub.calls, "Expected export_onnx to be invoked"
    call = stub.calls[0]
    assert call.model_id == "naver/splade-v3"
    assert call.quantization_config == "avx512"


def test_encode_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Encode should invoke the encoder service and persist metadata artifacts."""
    stub = _StubEncoderService(tmp_path)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(splade_cli, "_create_encoder_service", lambda: stub)

    source = tmp_path / "corpus.jsonl"
    source.write_text('{"id": "doc1", "contents": "text"}\n', encoding="utf-8")

    result = runner.invoke(
        root_app,
        [
            "splade",
            "encode",
            str(source),
            "--batch-size",
            "16",
        ],
    )

    assert result.exit_code == 0
    assert "Encoded corpus" in result.stdout
    assert stub.calls, "Expected encode_corpus to be invoked"
    _, options = stub.calls[0]
    assert options is not None
    assert options.batch_size == 16
    metadata_path = stub.tmp_path / "vectors" / "vectors_metadata.json"
    assert metadata_path.exists()


def test_build_index_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """build-index should dispatch to the index manager with parsed options."""
    stub = _StubIndexManager(tmp_path)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(splade_cli, "_create_index_manager", lambda: stub)

    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    result = runner.invoke(
        root_app,
        [
            "splade",
            "build-index",
            "--vectors-dir",
            str(vectors_dir),
            "--threads",
            "12",
            "--max-clause-count",
            "8192",
            "--no-overwrite",
        ],
    )

    assert result.exit_code == 0
    assert "Built impact index" in result.stdout
    assert stub.calls, "Expected build_index to be invoked"
    options = stub.calls[0]
    assert isinstance(options, SpladeBuildOptions)
    assert options.vectors_dir == vectors_dir
    assert options.threads == 12
    assert options.max_clause_count == 8192
    assert not options.overwrite
