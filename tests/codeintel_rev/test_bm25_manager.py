"""Tests for the BM25IndexManager."""

from __future__ import annotations

import json
from pathlib import Path

import msgspec
import pytest
from codeintel_rev.config.settings import Settings
from codeintel_rev.io.bm25_manager import (
    BM25CorpusMetadata,
    BM25IndexManager,
    BM25IndexMetadata,
)

from tests._helpers import assertions, constants
from tests._helpers.settings import build_settings_for_repo

DOC_COUNT = constants.BATCH_SIZES.minimal


def _bootstrap_repo(tmp_path: Path, *, bm25_threads: int | None = None) -> tuple[Path, Settings]:
    """Initialize a fake repository layout and return configured settings.

    Returns
    -------
    tuple[Path, Settings]
        Tuple containing the repo root path and tailored Settings instance.
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

    bm25_overrides = {"threads": bm25_threads} if bm25_threads is not None else None
    settings = build_settings_for_repo(repo_root, bm25_overrides=bm25_overrides)
    return repo_root, settings


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
    repo_root, settings = _bootstrap_repo(tmp_path)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    manager = BM25IndexManager(settings)

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
    repo_root, settings = _bootstrap_repo(tmp_path)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    rows = [
        {"id": "dup", "contents": "first"},
        {"id": "dup", "contents": "second"},
    ]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    manager = BM25IndexManager(settings)

    with pytest.raises(ValueError, match="Duplicate document id"):
        manager.prepare_corpus(source_path)


def test_build_index_writes_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Index builds should invoke Pyserini and persist index metadata."""
    repo_root, settings = _bootstrap_repo(tmp_path, bm25_threads=2)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    manager = BM25IndexManager(settings)
    summary = manager.prepare_corpus(source_path)

    created_command: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        created_command.append(cmd)
        resolved = manager.index_dir
        (resolved / "segments_1").write_text("stub", encoding="utf-8")

    monkeypatch.setattr("codeintel_rev.io.bm25_manager._run_pyserini_index", fake_run)
    monkeypatch.setattr("codeintel_rev.io.bm25_manager._detect_pyserini_version", lambda: "test")

    metadata = manager.build_index()

    assertions.expect_true(created_command, reason="Expected Pyserini command to be executed")
    command = created_command[0]
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
