"""Tests for the BM25IndexManager."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
from codeintel_rev.io.bm25_manager import (
    BM25BuildContext,
    BM25CorpusMetadata,
    BM25IndexManager,
    BM25IndexMetadata,
)

from kgfoundry_common.subprocess_utils import SubprocessError
from tests._helpers import assertions, constants

DOC_COUNT = constants.BATCH_SIZES.minimal


def _make_app_config(repo_root: Path, bm25_threads: int | None = None) -> AppConfig:
    """Return AppConfig for the synthetic repository.

    Parameters
    ----------
    repo_root : Path
        Repository root directory for configuration paths.
    bm25_threads : int | None, optional
        Optional BM25 thread count override, by default None.

    Returns
    -------
    AppConfig
        Immutable configuration anchored at ``repo_root``.
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
        threads=bm25_threads if bm25_threads is not None else 8,
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
            enable=True,
            mode="narrow",
        ),
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
        index=IndexSettings(),
    )


def _bootstrap_repo(tmp_path: Path, *, bm25_threads: int | None = None) -> tuple[Path, AppConfig]:
    """Initialize a fake repository layout and return configured AppConfig.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.
    bm25_threads : int | None, optional
        Optional BM25 thread count override, by default None.

    Returns
    -------
    tuple[Path, AppConfig]
        Tuple containing the repo root path and tailored AppConfig instance.
    """
    repo_root = tmp_path / "repo"
    data_dir = repo_root / "data"
    lucene_dir = repo_root / "indexes"
    bm25_json_dir = data_dir / "bm25_json"

    bm25_json_dir.mkdir(parents=True)
    (lucene_dir / "bm25").mkdir(parents=True)
    (repo_root / "data" / "vectors").mkdir(parents=True)
    (repo_root / "data" / "faiss").mkdir(parents=True)
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").touch()
    (repo_root / "index.scip").write_text("{}", encoding="utf-8")

    app_config = _make_app_config(repo_root, bm25_threads=bm25_threads)
    return repo_root, app_config


def _write_corpus(source_path: Path) -> None:
    """Generate a tiny JSONL corpus for testing."""
    rows = [
        {"id": "doc1", "contents": "Solar panels convert sunlight into electricity."},
        {"id": "doc2", "text": "Tax credits can reduce the cost of installing solar."},
    ]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_prepare_corpus_creates_json_collection(tmp_path: Path) -> None:
    """Preparing a corpus should emit per-document JSON and metadata."""
    repo_root, app_config = _bootstrap_repo(tmp_path)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    manager = BM25IndexManager(app_config)

    summary = manager.prepare_corpus(source_path)

    output_dir = Path(summary.output_dir)
    assertions.expect_true(output_dir.is_dir())
    doc_files = sorted(p.name for p in output_dir.glob("*.json") if p.name != "metadata.json")
    assertions.expect_sequence_equal(doc_files, ["doc1.json", "doc2.json"])
    assertions.expect_true((output_dir / "metadata.json").is_file())

    metadata_path = Path(summary.corpus_metadata_path)
    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=BM25CorpusMetadata)
    assertions.expect_equal(metadata.doc_count, DOC_COUNT)
    assertions.expect_equal(metadata.source_path, str(source_path.resolve()))
    assertions.expect_equal(metadata.digest, summary.digest)


def test_prepare_corpus_detects_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate document identifiers should cause preparation to fail."""
    repo_root, app_config = _bootstrap_repo(tmp_path)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    rows = [
        {"id": "dup", "contents": "first"},
        {"id": "dup", "contents": "second"},
    ]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    manager = BM25IndexManager(app_config)

    with pytest.raises(ValueError, match="Duplicate document id"):
        manager.prepare_corpus(source_path)


def test_build_index_writes_metadata(tmp_path: Path) -> None:
    """Index builds should invoke Pyserini and persist index metadata."""
    repo_root, app_config = _bootstrap_repo(tmp_path, bm25_threads=2)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    commands: list[list[str]] = []
    index_dir = Path(app_config.bm25.index_dir)

    def fake_runner(cmd: list[str]) -> None:
        """Record command and create stub index file for test.

        Parameters
        ----------
        cmd : list[str]
            Command arguments to record.
        """
        commands.append(list(cmd))
        (index_dir / "segments_1").write_text("stub", encoding="utf-8")

    context = replace(
        BM25BuildContext.production(),
        pyserini_runner=fake_runner,
        version_provider=lambda: "test",
        clock=lambda: datetime(2024, 1, 1, tzinfo=UTC),
    )

    manager = BM25IndexManager(app_config, build_context=context)
    summary = manager.prepare_corpus(source_path)

    metadata = manager.build_index()

    assertions.expect_true(commands, reason="Expected Pyserini command to be executed")
    command = commands[0]
    for token in ("--collection", "JsonCollection", "--input", summary.output_dir):
        assertions.expect_in(token, command)

    index_dir = Path(metadata.index_dir)
    assertions.expect_true(index_dir.is_dir())
    assertions.expect_true(metadata.index_size_bytes > 0)
    assertions.expect_equal(metadata.doc_count, DOC_COUNT)
    assertions.expect_equal(metadata.corpus_digest, summary.digest)
    assertions.expect_equal(metadata.pyserini_version, "test")

    disk_metadata = msgspec.json.decode(
        (index_dir / "metadata.json").read_bytes(),
        type=BM25IndexMetadata,
    )
    assertions.expect_equal(disk_metadata, metadata)


def test_build_index_raises_when_subprocess_fails(tmp_path: Path) -> None:
    """Pyserini failures should surface as SubprocessError."""
    _, app_config = _bootstrap_repo(tmp_path)

    def fake_run(cmd: list[str]) -> None:
        """Raise SubprocessError to test error handling.

        Parameters
        ----------
        cmd : list[str]
            Command arguments (unused).

        Raises
        ------
        SubprocessError
            Always raised with message "fail" and returncode 1.
        """
        _ = cmd
        message = "fail"
        raise SubprocessError(message, returncode=1)

    context = replace(
        BM25BuildContext.production(),
        pyserini_runner=fake_run,
    )
    manager = BM25IndexManager(app_config, build_context=context)

    with pytest.raises(SubprocessError):
        manager.build_index()
