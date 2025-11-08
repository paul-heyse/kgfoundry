"""CLI tests for bm25 maintenance commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from codeintel_rev.cli import app as root_app
from codeintel_rev.cli import bm25 as bm25_cli
from codeintel_rev.io.bm25_manager import (
    BM25BuildOptions,
    BM25CorpusSummary,
    BM25IndexMetadata,
)
from tools import Paths
from typer.testing import CliRunner

runner = CliRunner()


class _StubBM25Manager:
    """Stand-in manager that records invocations for CLI tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.prepare_calls: list[tuple[Path, Path | None, bool]] = []
        self.build_calls: list[BM25BuildOptions | None] = []
        self.last_corpus_metadata_path: Path | None = None
        self.last_index_metadata_path: Path | None = None

    def prepare_corpus(
        self,
        source: Path,
        *,
        output_dir: Path | None = None,
        overwrite: bool = True,
    ) -> BM25CorpusSummary:
        self.prepare_calls.append((source, output_dir, overwrite))
        json_dir = self.tmp_path / "bm25_json"
        json_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = json_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps({"doc_count": 2, "digest": "digest123"}),
            encoding="utf-8",
        )
        self.last_corpus_metadata_path = metadata_path
        return BM25CorpusSummary(
            doc_count=2,
            output_dir=str(json_dir),
            digest="digest123",
            corpus_metadata_path=str(metadata_path),
        )

    def build_index(self, options: BM25BuildOptions | None = None) -> BM25IndexMetadata:
        self.build_calls.append(options)
        index_dir = self.tmp_path / "bm25_index"
        index_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = index_dir / "metadata.json"
        metadata_path.write_text(json.dumps({"doc_count": 2}), encoding="utf-8")
        self.last_index_metadata_path = metadata_path
        return BM25IndexMetadata(
            doc_count=2,
            built_at="2025-01-01T00:00:00Z",
            corpus_digest="digest123",
            corpus_source="corpus.jsonl",
            pyserini_version="stub",
            threads=(options.threads if options and options.threads is not None else 2),
            index_dir=str(index_dir),
            index_size_bytes=128,
            generator="test",
        )


def _patch_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect CLI envelope output to a temporary path."""
    Paths.discover.cache_clear()

    def fake_discover(_start: Path | None = None) -> Paths:
        return Paths(
            repo_root=tmp_path,
            docs_data=tmp_path / "docs",
            cli_out_root=tmp_path / "cli",
        )

    monkeypatch.setattr(Paths, "discover", staticmethod(fake_discover))


def test_prepare_corpus_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """prepare-corpus should invoke the manager and emit user-facing output."""
    stub = _StubBM25Manager(tmp_path)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(bm25_cli, "_create_bm25_manager", lambda: stub)

    source = tmp_path / "corpus.jsonl"
    source.write_text('{"id": "doc1", "contents": "text"}\n', encoding="utf-8")

    result = runner.invoke(root_app, ["bm25", "prepare-corpus", str(source)])

    assert result.exit_code == 0
    assert "Prepared 2 documents" in result.stdout
    assert stub.prepare_calls == [(source, None, True)]
    assert stub.last_corpus_metadata_path is not None
    assert stub.last_corpus_metadata_path.exists()


def test_build_index_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """build-index should interpret CLI flags and dispatch to the manager."""
    stub = _StubBM25Manager(tmp_path)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(bm25_cli, "_create_bm25_manager", lambda: stub)

    json_dir = tmp_path / "prepared"
    json_dir.mkdir()

    result = runner.invoke(
        root_app,
        [
            "bm25",
            "build-index",
            "--json-dir",
            str(json_dir),
            "--threads",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert "Built index" in result.stdout
    assert stub.build_calls, "Expected build_index to be invoked"

    options = stub.build_calls[0]
    assert isinstance(options, BM25BuildOptions)
    assert options.json_dir == json_dir
    assert options.threads == 4
    assert stub.last_index_metadata_path is not None
    assert stub.last_index_metadata_path.exists()
