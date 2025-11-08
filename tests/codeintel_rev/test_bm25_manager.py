"""Tests for the BM25IndexManager."""

from __future__ import annotations

import json
from pathlib import Path

import msgspec
import pytest
from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.bm25_manager import (
    BM25CorpusMetadata,
    BM25IndexManager,
    BM25IndexMetadata,
)


def _bootstrap_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a fake repository layout and configure environment variables.

    Returns
    -------
    Path
        The absolute path to the synthetic repository root.
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

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAISS_INDEX", str(repo_root / "data" / "faiss" / "code.ivfpq.faiss"))
    monkeypatch.setenv("DUCKDB_PATH", str(repo_root / "data" / "catalog.duckdb"))
    monkeypatch.setenv("SCIP_INDEX", str(repo_root / "index.scip"))
    monkeypatch.setenv("BM25_JSONL_DIR", str(bm25_json_dir))
    monkeypatch.setenv("BM25_INDEX_DIR", str(lucene_dir / "bm25"))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    return repo_root


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


def test_prepare_corpus_creates_json_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preparing a corpus should emit per-document JSON and metadata."""
    repo_root = _bootstrap_repo(tmp_path, monkeypatch)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    settings = load_settings()
    manager = BM25IndexManager(settings)

    summary = manager.prepare_corpus(source_path)

    output_dir = Path(summary.output_dir)
    assert output_dir.is_dir()
    doc_files = sorted(p.name for p in output_dir.glob("*.json") if p.name != "metadata.json")
    assert doc_files == ["doc1.json", "doc2.json"]
    assert (output_dir / "metadata.json").is_file()

    metadata_path = Path(summary.corpus_metadata_path)
    metadata = msgspec.json.decode(metadata_path.read_bytes(), type=BM25CorpusMetadata)
    assert metadata.doc_count == 2
    assert metadata.source_path == str(source_path.resolve())
    assert metadata.digest == summary.digest


def test_prepare_corpus_detects_duplicate_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate document identifiers should cause preparation to fail."""
    repo_root = _bootstrap_repo(tmp_path, monkeypatch)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    rows = [
        {"id": "dup", "contents": "first"},
        {"id": "dup", "contents": "second"},
    ]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    settings = load_settings()
    manager = BM25IndexManager(settings)

    with pytest.raises(ValueError, match="Duplicate document id"):
        manager.prepare_corpus(source_path)


def test_build_index_writes_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Index builds should invoke Pyserini and persist index metadata."""
    repo_root = _bootstrap_repo(tmp_path, monkeypatch)
    source_path = repo_root / "datasets" / "corpus.jsonl"
    _write_corpus(source_path)

    settings = load_settings()
    manager = BM25IndexManager(settings)
    summary = manager.prepare_corpus(source_path)

    created_command: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        created_command.append(cmd)
        resolved = manager.index_dir
        (resolved / "segments_1").write_text("stub", encoding="utf-8")

    monkeypatch.setenv("BM25_THREADS", "2")
    monkeypatch.setattr("codeintel_rev.io.bm25_manager._run_pyserini_index", fake_run)
    monkeypatch.setattr("codeintel_rev.io.bm25_manager._detect_pyserini_version", lambda: "test")

    metadata = manager.build_index()

    assert created_command, "Expected Pyserini command to be executed"
    command = created_command[0]
    assert "--collection" in command
    assert "JsonCollection" in command
    assert "--input" in command
    assert summary.output_dir in command

    index_dir = Path(metadata.index_dir)
    assert index_dir.is_dir()
    assert metadata.index_size_bytes > 0
    assert metadata.doc_count == 2
    assert metadata.corpus_digest == summary.digest
    assert metadata.pyserini_version == "test"

    disk_metadata = msgspec.json.decode(
        (index_dir / "metadata.json").read_bytes(),
        type=BM25IndexMetadata,
    )
    assert disk_metadata == metadata
