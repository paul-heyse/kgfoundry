"""CLI tests for bm25 maintenance commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from click.testing import Result
from codeintel_rev.cli import app as root_app
from codeintel_rev.cli.bm25 import BM25CliContext
from codeintel_rev.io.bm25_manager import (
    BM25BuildOptions,
    BM25CorpusSummary,
    BM25IndexManager,
    BM25IndexMetadata,
)
from typer.testing import CliRunner

from tests._helpers import assertions, constants

runner = CliRunner()
DOC_COUNT = constants.BATCH_SIZES.minimal
THREAD_OVERRIDE = constants.BATCH_SIZES.medium


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
        """Prepare corpus and record call.

        Parameters
        ----------
        source : Path
            Source corpus path to record.
        output_dir : Path | None, optional
            Output directory (unused).
        overwrite : bool, optional
            Overwrite flag to record.

        Returns
        -------
        BM25CorpusSummary
            Stub corpus summary with metadata paths.
        """
        self.prepare_calls.append((source, output_dir, overwrite))
        json_dir = self.tmp_path / "bm25_json"
        json_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = json_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps({"doc_count": DOC_COUNT, "digest": "digest123"}),
            encoding="utf-8",
        )
        self.last_corpus_metadata_path = metadata_path
        return BM25CorpusSummary(
            doc_count=DOC_COUNT,
            output_dir=str(json_dir),
            digest="digest123",
            corpus_metadata_path=str(metadata_path),
        )

    def build_index(self, options: BM25BuildOptions | None = None) -> BM25IndexMetadata:
        """Build index and record call.

        Parameters
        ----------
        options : BM25BuildOptions | None, optional
            Build options to record.

        Returns
        -------
        BM25IndexMetadata
            Stub index metadata with test values.
        """
        self.build_calls.append(options)
        index_dir = self.tmp_path / "bm25_index"
        index_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = index_dir / "metadata.json"
        metadata_path.write_text(json.dumps({"doc_count": DOC_COUNT}), encoding="utf-8")
        self.last_index_metadata_path = metadata_path
        return BM25IndexMetadata(
            doc_count=DOC_COUNT,
            built_at="2025-01-01T00:00:00Z",
            corpus_digest="digest123",
            corpus_source="corpus.jsonl",
            pyserini_version="stub",
            threads=(
                options.threads
                if options and options.threads is not None
                else constants.BATCH_SIZES.minimal
            ),
            index_dir=str(index_dir),
            index_size_bytes=128,
            generator="test",
        )


def _invoke_bm25(
    args: list[str],
    *,
    context: BM25CliContext,
    envelope_dir: Path,
) -> Result:
    return runner.invoke(
        root_app,
        [
            "bm25",
            *args,
        ],
        obj={
            "bm25_cli_context": context,
            "cli_run_overrides": {"envelope_dir": envelope_dir},
        },
    )


def test_prepare_corpus_cli(
    tmp_path: Path,
    bm25_cli_context_builder: Callable[..., BM25CliContext],
) -> None:
    """prepare-corpus should invoke the manager and emit user-facing output."""
    stub = _StubBM25Manager(tmp_path)
    context = bm25_cli_context_builder(manager_factory=lambda: cast("BM25IndexManager", stub))

    source = tmp_path / "corpus.jsonl"
    source.write_text('{"id": "doc1", "contents": "text"}\n', encoding="utf-8")

    result = _invoke_bm25(
        [
            "prepare-corpus",
            str(source),
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Prepared 2 documents", result.stdout)
    assertions.expect_sequence_equal(stub.prepare_calls, [(source, None, True)])
    assertions.expect_true(stub.last_corpus_metadata_path is not None)
    if stub.last_corpus_metadata_path:
        assertions.expect_true(stub.last_corpus_metadata_path.exists())


def test_build_index_cli(
    tmp_path: Path,
    bm25_cli_context_builder: Callable[..., BM25CliContext],
) -> None:
    """build-index should interpret CLI flags and dispatch to the manager."""
    stub = _StubBM25Manager(tmp_path)
    context = bm25_cli_context_builder(manager_factory=lambda: cast("BM25IndexManager", stub))

    json_dir = tmp_path / "prepared"
    json_dir.mkdir()

    result = _invoke_bm25(
        [
            "build-index",
            "--json-dir",
            str(json_dir),
            "--threads",
            str(THREAD_OVERRIDE),
        ],
        context=context,
        envelope_dir=tmp_path / "envelopes",
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("Built index", result.stdout)
    assertions.expect_true(bool(stub.build_calls))

    options = stub.build_calls[0]
    assertions.expect_true(isinstance(options, BM25BuildOptions))
    if not isinstance(options, BM25BuildOptions):  # pragma: no cover - type guard
        pytest.fail("build calls should include BM25BuildOptions")
    assertions.expect_equal(options.json_dir, json_dir)
    assertions.expect_equal(options.threads, THREAD_OVERRIDE)
    assertions.expect_true(stub.last_index_metadata_path is not None)
    if stub.last_index_metadata_path:
        assertions.expect_true(stub.last_index_metadata_path.exists())
