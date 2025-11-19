"""Tests for SPLADE artifact and index management."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import msgspec
import pytest
from codeintel_rev.config.api import (
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    EmbeddingsSettings,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)
from codeintel_rev.io.splade_manager import (
    SpladeArtifactMetadata,
    SpladeArtifactsContext,
    SpladeArtifactsManager,
    SpladeBenchmarkOptions,
    SpladeBuildOptions,
    SpladeEncodeOptions,
    SpladeEncoderContext,
    SpladeEncoderService,
    SpladeEncodingMetadata,
    SpladeExportOptions,
    SpladeIndexContext,
    SpladeIndexManager,
    SpladeIndexMetadata,
)

from kgfoundry_common.subprocess_utils import SubprocessError

if TYPE_CHECKING:
    from codeintel_rev.io.splade_manager import _SparseEncoderProtocol
from tests._helpers import assertions


def _make_app_config(repo_root: Path) -> AppConfig:
    """Return an AppConfig populated with repo-relative defaults.

    Returns
    -------
    AppConfig
        Immutable configuration referencing ``repo_root``.
    """
    data_dir = repo_root / "data"
    paths = PathsConfig(
        repo_root=repo_root,
        data_dir=data_dir,
        cache_dir=repo_root / ".cache",
        logs_dir=repo_root / "logs",
    )
    duck_cfg = DuckDBSettings(database=data_dir / "catalog.duckdb")
    faiss_cfg = FAISSSettings(index_path=data_dir / "faiss" / "code.ivfpq.faiss")
    bm25_cfg = BM25Settings(
        corpus_json_dir=data_dir / "bm25_json",
        index_dir=repo_root / "indexes" / "bm25",
        threads=8,
        enabled=True,
        k1=0.9,
        b=0.4,
        rm3_enabled=False,
        rm3_fb_docs=10,
        rm3_fb_terms=10,
        rm3_original_query_weight=0.5,
        analyzer="code",
    )
    splade_cfg = SpladeSettings(
        model_id="naver/splade-v3",
        model_dir=repo_root / "models" / "splade-v3",
        onnx_dir=repo_root / "models" / "splade-v3" / "onnx",
        onnx_file="model_qint8.onnx",
        vectors_dir=data_dir / "splade_vectors",
        index_dir=repo_root / "indexes" / "splade_v3_impact",
        provider="CPUExecutionProvider",
        quantization=100,
        max_terms=3000,
        max_clause_count=4096,
        batch_size=32,
        threads=8,
        enabled=True,
        max_query_terms=64,
        prune_below=0.0,
        analyzer="wordpiece",
        static_prune_pct=0.0,
    )
    return AppConfig(
        version="1.0",
        paths=paths,
        duckdb=duck_cfg,
        faiss=faiss_cfg,
        bm25=bm25_cfg,
        splade=splade_cfg,
        xtr=XTRSettings(
            model_id="nomic-ai/CodeRankEmbed",
            device="cuda",
            max_query_tokens=256,
            candidate_k=200,
            dim=768,
            dtype="float16",
            enable=False,
            mode="narrow",
        ),
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
        index=IndexSettings(),
    )


def _bootstrap_repo(tmp_path: Path) -> tuple[Path, AppConfig]:
    """Prepare a synthetic repository layout and corresponding AppConfig.

    Returns
    -------
    tuple[Path, AppConfig]
        Tuple containing repo root path and configured AppConfig.
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

    app_config = _make_app_config(repo_root)
    splade_cfg = replace(
        app_config.splade,
        threads=4,
        batch_size=8,
        model_dir=repo_root / "models" / "splade-v3",
        onnx_dir=models_dir,
        vectors_dir=vectors_dir,
        index_dir=splade_index_dir,
    )
    app_config = replace(app_config, splade=splade_cfg)
    return repo_root, app_config


def _stub_save_pretrained(path: str) -> None:
    """Stub save_pretrained function for testing.

    Parameters
    ----------
    path : str
        Path to save the model.
    """
    base = Path(path)
    onnx_dir = base / "onnx"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    (onnx_dir / "model.onnx").write_text("base", encoding="utf-8")


class _StubEncoder:
    """Stub SparseEncoder implementation for encode/export tests."""

    def __init__(
        self,
        model_dir: str,
        *,
        backend: str,
        model_kwargs: Mapping[str, object] | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.backend = backend
        self.model_kwargs = dict(model_kwargs or {})
        self._last_texts: list[str] = []

    @staticmethod
    def save_pretrained(path: str) -> None:
        """Save pretrained model stub.

        Parameters
        ----------
        path : str
            Path to save the model.
        """
        _stub_save_pretrained(path)

    def encode_document(self, sentences: Sequence[str]) -> Sequence[int]:
        """Encode document texts stub.

        Parameters
        ----------
        sentences : Sequence[str]
            Texts to encode.

        Returns
        -------
        list[int]
            Encoded token IDs.
        """
        self._last_texts = list(sentences)
        return list(range(len(sentences)))

    def encode_query(self, texts: Sequence[str]) -> Sequence[int]:
        """Encode query texts stub.

        Parameters
        ----------
        texts : Sequence[str]
            Texts to encode.

        Returns
        -------
        list[int]
            Encoded token IDs.
        """
        self._last_texts = list(texts)
        return list(range(len(texts)))

    def decode(
        self,
        embeddings: object,
        top_k: int | None = None,
    ) -> Sequence[Sequence[tuple[str, float]]]:
        """Decode embeddings stub.

        Parameters
        ----------
        embeddings : object
            Embedding vectors to decode.
        top_k : int | None, optional
            Number of top tokens to return, by default None.

        Returns
        -------
        Sequence[Sequence[tuple[str, float]]]
            Decoded token scores.
        """
        _ = embeddings, top_k
        return [[("solar", 0.4), ("energy", 0.2)] for _ in self._last_texts]


def _build_stub_encoder_factory() -> Callable[[], Callable[..., _SparseEncoderProtocol]]:
    def _factory(
        model_id: str,
        *,
        backend: str,
        model_kwargs: Mapping[str, object] | None = None,
    ) -> _SparseEncoderProtocol:
        encoder = _StubEncoder(
            model_id,
            backend=backend,
            model_kwargs=dict(model_kwargs or {}),
        )
        return cast("_SparseEncoderProtocol", encoder)

    return lambda: _factory


def test_export_onnx_writes_metadata(tmp_path: Path) -> None:
    """Exporting ONNX artifacts should persist metadata and respect configuration overrides."""
    _, app_config = _bootstrap_repo(tmp_path)
    encoder_context = SpladeEncoderContext(encoder_factory=_build_stub_encoder_factory())

    def fake_export_helpers() -> tuple[Callable[..., None], Callable[..., None]]:
        onnx_dir = app_config.splade.onnx_dir

        def optimizer(**_: object) -> None:
            (onnx_dir / "model_O3.onnx").write_text("optimized", encoding="utf-8")

        def quantizer(**_: object) -> None:
            (onnx_dir / "model_qint8.onnx").write_text("quantized", encoding="utf-8")

        return optimizer, quantizer

    artifacts_context = SpladeArtifactsContext(
        encoder_context=encoder_context,
        export_helpers_factory=fake_export_helpers,
        clock=lambda: datetime(2024, 1, 1, tzinfo=UTC),
    )
    manager = SpladeArtifactsManager(app_config, artifacts_context=artifacts_context)

    summary = manager.export_onnx(
        SpladeExportOptions(
            model_id="naver/splade-v3",
            provider="CPUExecutionProvider",
            quantization_config="avx512",
        ),
    )

    assertions.expect_true(
        summary.onnx_file.endswith("model_qint8.onnx"),
        reason="onnx_file should end with model_qint8.onnx",
    )
    metadata_path = Path(summary.metadata_path)
    assertions.expect_true(metadata_path.exists(), reason="metadata_path should exist")

    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeArtifactMetadata)
    assertions.expect_equal(metadata.model_id, "naver/splade-v3")
    assertions.expect_equal(metadata.provider, "CPUExecutionProvider")
    assertions.expect_true(metadata.quantized, reason="metadata should be quantized")
    assertions.expect_true(metadata.optimized, reason="metadata should be optimized")
    assertions.expect_equal(metadata.quantization_config, "avx512")


def test_encode_corpus_writes_vectors(
    tmp_path: Path,
) -> None:
    """Encoding should emit JsonVectorCollection shards and metadata."""
    repo_root, app_config = _bootstrap_repo(tmp_path)
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

    encoder_context = SpladeEncoderContext(encoder_factory=_build_stub_encoder_factory())
    service = SpladeEncoderService(app_config, encoder_context=encoder_context)

    summary = service.encode_corpus(
        source,
        SpladeEncodeOptions(shard_size=1),
    )

    metadata_path = Path(summary.metadata_path)
    assertions.expect_true(metadata_path.exists(), reason="metadata_path should exist")
    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeEncodingMetadata)
    assertions.expect_equal(metadata.doc_count, 2)
    assertions.expect_equal(metadata.quantization, 100)

    shard = Path(summary.vectors_dir) / "part-00000.jsonl"
    assertions.expect_true(shard.exists(), reason="shard file should exist")
    content = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assertions.expect_equal(content["id"], "doc1")
    assertions.expect_true(
        content["vector"]["solar"] > 0, reason="solar vector value should be positive"
    )


def test_benchmark_queries_reports_latency(tmp_path: Path) -> None:
    """Benchmarking should report latency percentiles for SPLADE query encoding."""
    repo_root, app_config = _bootstrap_repo(tmp_path)
    quantized_file = Path(repo_root / "models" / "splade-v3" / "onnx" / "model_qint8.onnx")
    quantized_file.write_text("quantized", encoding="utf-8")

    encoder_context = SpladeEncoderContext(encoder_factory=_build_stub_encoder_factory())
    timings = iter([0.0, 0.005, 0.100, 0.120, 0.200, 0.240])
    service = SpladeEncoderService(
        app_config,
        encoder_context=encoder_context,
        timer=lambda: next(timings),
    )

    summary = service.benchmark_queries(
        ["renewable energy"],
        SpladeBenchmarkOptions(warmup_iterations=1, measure_iterations=3),
    )

    assertions.expect_equal(summary.query_count, 1)
    assertions.expect_equal(summary.warmup_iterations, 1)
    assertions.expect_equal(summary.measure_iterations, 3)
    assertions.expect_almost_equal(summary.min_latency_ms, 5.0)
    assertions.expect_almost_equal(summary.max_latency_ms, 40.0)
    assertions.expect_almost_equal(summary.p50_latency_ms, 20.0)
    assertions.expect_almost_equal(summary.p95_latency_ms, 38.0)
    assertions.expect_equal(summary.provider, "CPUExecutionProvider")
    assertions.expect_equal(summary.onnx_file, "onnx/model_qint8.onnx")


def test_build_index_persists_metadata(tmp_path: Path) -> None:
    """Index builds should invoke Pyserini via subprocess and record metadata."""
    _, app_config = _bootstrap_repo(tmp_path)
    vectors_dir = app_config.splade.vectors_dir
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

    def fake_run(cmd: list[str], env: dict[str, str] | None = None) -> str:
        captured_commands.append(cmd)
        _ = env
        index_dir = app_config.splade.index_dir
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "segments_1").write_text("stub", encoding="utf-8")
        return ""

    index_context = replace(
        SpladeIndexContext.production(),
        subprocess_runner=fake_run,
        version_provider=lambda: "test",
        clock=lambda: datetime(2024, 1, 1, tzinfo=UTC),
    )
    manager = SpladeIndexManager(app_config, index_context=index_context)

    metadata = manager.build_index(
        SpladeBuildOptions(
            max_clause_count=8192,
            overwrite=True,
        ),
    )

    assertions.expect_true(bool(captured_commands), reason="Expected run_subprocess to be invoked")
    assertions.expect_equal(metadata.doc_count, 3)
    assertions.expect_equal(metadata.pyserini_version, "test")
    assertions.expect_true(
        metadata.index_size_bytes > 0, reason="index_size_bytes should be positive"
    )

    disk_metadata = msgspec.json.decode(
        (Path(metadata.index_dir) / "metadata.json").read_bytes(),
        type=SpladeIndexMetadata,
    )
    assertions.expect_equal(disk_metadata, metadata)


def test_build_index_raises_when_subprocess_fails(tmp_path: Path) -> None:
    """Pyserini failures should surface as SubprocessError."""
    _, app_config = _bootstrap_repo(tmp_path)

    def fake_run(cmd: list[str], env: dict[str, str] | None = None) -> str:
        _ = cmd, env
        message = "fail"
        raise SubprocessError(message, returncode=1)

    index_context = replace(
        SpladeIndexContext.production(),
        subprocess_runner=fake_run,
    )
    manager = SpladeIndexManager(app_config, index_context=index_context)

    with pytest.raises(SubprocessError):
        manager.build_index()
