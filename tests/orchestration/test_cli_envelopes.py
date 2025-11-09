"""Tests for the orchestration CLI envelope integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from kgfoundry_common.vector_types import VectorValidationError
from orchestration import cli as orchestration_cli


@pytest.fixture(name="runner")
def _runner() -> CliRunner:
    return CliRunner()


def _read_envelope(path: Path) -> dict[str, object]:
    payload = path.read_text(encoding="utf-8")
    return cast("dict[str, object]", json.loads(payload))


def test_index_bm25_emits_success_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.setattr(orchestration_cli, "CLI_ENVELOPE_DIR", tmp_path)

    def fake_build(
        config: orchestration_cli.BM25BuildConfig,
        *,
        logger: orchestration_cli.LoggerAdapter,
    ) -> tuple[str, int]:
        assert isinstance(config, orchestration_cli.BM25BuildConfig)
        assert isinstance(logger, orchestration_cli.LoggerAdapter)
        return "lucene", 3

    monkeypatch.setattr(orchestration_cli, "_build_bm25_index", fake_build)

    chunks_file = tmp_path / "chunks.jsonl"
    chunks_file.write_text("{}\n", encoding="utf-8")

    result = runner.invoke(
        orchestration_cli.app,
        [
            "index-bm25",
            str(chunks_file),
            "--backend",
            "lucene",
            "--index-dir",
            str(tmp_path / "_indices" / "bm25"),
        ],
    )

    assert result.exit_code == 0
    envelope_path = tmp_path / "kgf-orchestration-index-bm25.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "success"
    files = cast("list[dict[str, object]]", envelope["files"])
    assert any(cast("str", entry.get("path", "")).endswith("bm25_index") for entry in files)


def test_index_faiss_records_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.setattr(orchestration_cli, "CLI_ENVELOPE_DIR", tmp_path)

    error = VectorValidationError("invalid payload", errors=["row 1: missing vector"])

    def fake_run(*, config: orchestration_cli.IndexCliConfig) -> dict[str, object]:
        assert isinstance(config, orchestration_cli.IndexCliConfig)
        raise error

    monkeypatch.setattr(orchestration_cli, "run_index_faiss", fake_run)

    vectors_file = tmp_path / "vectors.json"
    vectors_file.write_text("[]", encoding="utf-8")

    result = runner.invoke(
        orchestration_cli.app,
        [
            "index-faiss",
            str(vectors_file),
            "--index-path",
            str(tmp_path / "out.idx"),
        ],
    )

    assert result.exit_code == 1
    envelope_path = tmp_path / "kgf-orchestration-index-faiss.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "violation"
    problem = cast("dict[str, object]", envelope["problem"])
    assert problem["type"] == "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
    assert problem["vector_path"] == str(vectors_file)
    assert problem["errors"] == ["row 1: missing vector"]
