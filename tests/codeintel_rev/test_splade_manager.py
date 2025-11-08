"""Tests for SPLADE artifact and index management."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import msgspec
import pytest
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.splade_manager import (
    SpladeArtifactMetadata,
    SpladeArtifactsManager,
    SpladeBenchmarkOptions,
    SpladeBuildOptions,
    SpladeEncodeOptions,
    SpladeEncoderService,
    SpladeEncodingMetadata,
    SpladeExportOptions,
    SpladeIndexManager,
    SpladeIndexMetadata,
)

from kgfoundry_common.subprocess_utils import SubprocessError


def _bootstrap_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Prepare a synthetic repository layout with SPLADE environment variables.

    Returns
    -------
    Path
        Absolute path to the synthetic repository root.
    """
    repo_root = tmp_path / "repo"
    models_dir = repo_root / "models" / "splade-v3" / "onnx"
    vectors_dir = repo_root / "data" / "splade_vectors"
    bm25_dir = repo_root / "indexes" / "bm25"
    splade_index_dir = repo_root / "indexes" / "splade_v3_impact"
    faiss_dir = repo_root / "data" / "faiss"

    models_dir.mkdir(parents=True)
    vectors_dir.mkdir(parents=True)
    bm25_dir.mkdir(parents=True)
    splade_index_dir.mkdir(parents=True)
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").parent.mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "catalog.duckdb").touch()
    (repo_root / "index.scip").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("DATA_DIR", str(repo_root / "data"))
    monkeypatch.setenv("FAISS_INDEX", str(faiss_dir / "code.ivfpq.faiss"))
    monkeypatch.setenv("DUCKDB_PATH", str(repo_root / "data" / "catalog.duckdb"))
    monkeypatch.setenv("SCIP_INDEX", str(repo_root / "index.scip"))
    monkeypatch.setenv("BM25_JSONL_DIR", str(repo_root / "data" / "jsonl"))
    monkeypatch.setenv("BM25_INDEX_DIR", str(bm25_dir))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    monkeypatch.setenv("SPLADE_MODEL_ID", "naver/splade-v3")
    monkeypatch.setenv("SPLADE_MODEL_DIR", str(repo_root / "models" / "splade-v3"))
    monkeypatch.setenv("SPLADE_ONNX_DIR", str(models_dir))
    monkeypatch.setenv("SPLADE_ONNX_FILE", "model_qint8.onnx")
    monkeypatch.setenv("SPLADE_VECTORS_DIR", str(vectors_dir))
    monkeypatch.setenv("SPLADE_INDEX_DIR", str(splade_index_dir))
    monkeypatch.setenv("SPLADE_PROVIDER", "CPUExecutionProvider")
    monkeypatch.setenv("SPLADE_QUANTIZATION", "100")
    monkeypatch.setenv("SPLADE_MAX_TERMS", "3000")
    monkeypatch.setenv("SPLADE_MAX_CLAUSE", "4096")
    monkeypatch.setenv("SPLADE_BATCH_SIZE", "8")
    monkeypatch.setenv("SPLADE_THREADS", "4")

    return repo_root


class _StubEncoder:
    """Stub SparseEncoder implementation for encode/export tests."""

    def __init__(
        self, model_dir: str, *, backend: str, model_kwargs: dict[str, Any] | None = None
    ) -> None:
        self.model_dir = model_dir
        self.backend = backend
        self.model_kwargs = model_kwargs or {}
        self._last_texts: list[str] = []

    def save_pretrained(self, path: str) -> None:
        base = Path(path)
        onnx_dir = base / "onnx"
        onnx_dir.mkdir(parents=True, exist_ok=True)
        (onnx_dir / "model.onnx").write_text("base", encoding="utf-8")

    def encode_document(self, texts: list[str]) -> list[int]:
        self._last_texts = list(texts)
        return list(range(len(texts)))

    def encode_query(self, texts: list[str]) -> list[int]:
        self._last_texts = list(texts)
        return list(range(len(texts)))

    def decode(
        self,
        embeddings: Any,
        top_k: int | None = None,
    ) -> list[list[tuple[str, float]]]:
        _ = embeddings, top_k
        return [[("solar", 0.4), ("energy", 0.2)] for _ in self._last_texts]


def test_export_onnx_writes_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Exporting ONNX artifacts should persist metadata and respect configuration overrides."""
    _bootstrap_repo(tmp_path, monkeypatch)
    settings = load_settings()
    manager = SpladeArtifactsManager(settings)

    monkeypatch.setattr(
        "codeintel_rev.io.splade_manager._require_sparse_encoder", lambda: _StubEncoder
    )

    def fake_export_helpers() -> tuple[Callable[..., None], Callable[..., None]]:
        onnx_dir = Path(settings.splade.onnx_dir)

        def optimizer(**_: object) -> None:
            (onnx_dir / "model_O3.onnx").write_text("optimized", encoding="utf-8")

        def quantizer(**_: object) -> None:
            (onnx_dir / "model_qint8.onnx").write_text("quantized", encoding="utf-8")

        return optimizer, quantizer

    monkeypatch.setattr(
        "codeintel_rev.io.splade_manager._require_export_helpers", fake_export_helpers
    )

    summary = manager.export_onnx(
        SpladeExportOptions(
            model_id="naver/splade-v3",
            provider="CPUExecutionProvider",
            quantization_config="avx512",
        ),
    )

    assert summary.onnx_file.endswith("model_qint8.onnx")
    metadata_path = Path(summary.metadata_path)
    assert metadata_path.exists()

    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeArtifactMetadata)
    assert metadata.model_id == "naver/splade-v3"
    assert metadata.provider == "CPUExecutionProvider"
    assert metadata.quantized
    assert metadata.optimized
    assert metadata.quantization_config == "avx512"


def test_encode_corpus_writes_vectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Encoding should emit JsonVectorCollection shards and metadata."""
    repo_root = _bootstrap_repo(tmp_path, monkeypatch)
    source = repo_root / "datasets" / "corpus.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"id": "doc1", "contents": "Solar panels convert sunlight."},
        {"id": "doc2", "text": "Tax credits help adoption."},
    ]
    with source.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    quantized_file = Path(repo_root / "models" / "splade-v3" / "onnx" / "model_qint8.onnx")
    quantized_file.write_text("quantized", encoding="utf-8")

    settings = load_settings()
    service = SpladeEncoderService(settings)

    monkeypatch.setattr(
        "codeintel_rev.io.splade_manager._require_sparse_encoder", lambda: _StubEncoder
    )

    summary = service.encode_corpus(
        source,
        SpladeEncodeOptions(shard_size=1),
    )

    metadata_path = Path(summary.metadata_path)
    assert metadata_path.exists()
    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeEncodingMetadata)
    assert metadata.doc_count == 2
    assert metadata.quantization == 100

    shard = Path(summary.vectors_dir) / "part-00000.jsonl"
    assert shard.exists()
    content = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assert content["id"] == "doc1"
    assert content["vector"]["solar"] > 0


def test_benchmark_queries_reports_latency(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Benchmarking should report latency percentiles for SPLADE query encoding."""
    repo_root = _bootstrap_repo(tmp_path, monkeypatch)
    quantized_file = Path(repo_root / "models" / "splade-v3" / "onnx" / "model_qint8.onnx")
    quantized_file.write_text("quantized", encoding="utf-8")

    settings = load_settings()
    service = SpladeEncoderService(settings)

    monkeypatch.setattr(
        "codeintel_rev.io.splade_manager._require_sparse_encoder", lambda: _StubEncoder
    )

    timings = iter([0.0, 0.005, 0.100, 0.120, 0.200, 0.240])
    monkeypatch.setattr(
        "codeintel_rev.io.splade_manager.perf_counter",
        lambda: next(timings),
    )

    summary = service.benchmark_queries(
        ["renewable energy"],
        SpladeBenchmarkOptions(warmup_iterations=1, measure_iterations=3),
    )

    assert summary.query_count == 1
    assert summary.warmup_iterations == 1
    assert summary.measure_iterations == 3
    assert summary.min_latency_ms == pytest.approx(5.0, rel=1e-3)
    assert summary.max_latency_ms == pytest.approx(40.0, rel=1e-3)
    assert summary.p50_latency_ms == pytest.approx(20.0, rel=1e-3)
    assert summary.p95_latency_ms == pytest.approx(38.0, rel=1e-3)
    assert summary.provider == "CPUExecutionProvider"
    assert summary.onnx_file == "onnx/model_qint8.onnx"


def test_build_index_persists_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Index builds should invoke Pyserini via subprocess and record metadata."""
    _bootstrap_repo(tmp_path, monkeypatch)
    settings = load_settings()
    manager = SpladeIndexManager(settings)

    vectors_dir = Path(settings.splade.vectors_dir)
    metadata_struct = SpladeEncodingMetadata(
        doc_count=3,
        shard_count=1,
        quantization=100,
        batch_size=8,
        provider="CPUExecutionProvider",
        vectors_dir=str(vectors_dir),
        source_path=str(vectors_dir / ".." / "corpus.jsonl"),
        prepared_at="2025-01-01T00:00:00Z",
        generator="test",
    )
    (vectors_dir / "vectors_metadata.json").write_text(
        msgspec.json.encode(metadata_struct).decode(),
        encoding="utf-8",
    )

    captured_commands: list[list[str]] = []

    def fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
        captured_commands.append(cmd)
        _ = env
        index_dir = Path(settings.splade.index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "segments_1").write_text("stub", encoding="utf-8")

    monkeypatch.setattr("codeintel_rev.io.splade_manager.run_subprocess", fake_run)
    monkeypatch.setattr("codeintel_rev.io.splade_manager._detect_pyserini_version", lambda: "test")

    metadata = manager.build_index(
        SpladeBuildOptions(
            max_clause_count=8192,
            overwrite=True,
        ),
    )

    assert captured_commands, "Expected run_subprocess to be invoked"
    assert metadata.doc_count == 3
    assert metadata.pyserini_version == "test"
    assert metadata.index_size_bytes > 0

    disk_metadata = msgspec.json.decode(
        (Path(metadata.index_dir) / "metadata.json").read_bytes(),
        type=SpladeIndexMetadata,
    )
    assert disk_metadata == metadata


def test_build_index_raises_when_subprocess_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pyserini failures should surface as SubprocessError."""
    _bootstrap_repo(tmp_path, monkeypatch)
    settings = load_settings()
    manager = SpladeIndexManager(settings)

    def fake_run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
        _ = cmd, env
        message = "fail"
        raise SubprocessError(message, returncode=1)

    monkeypatch.setattr("codeintel_rev.io.splade_manager.run_subprocess", fake_run)

    with pytest.raises(SubprocessError):
        manager.build_index()
