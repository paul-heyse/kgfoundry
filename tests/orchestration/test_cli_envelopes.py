"""Tests for the orchestration CLI envelope integration."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from kgfoundry_common.vector_types import VectorValidationError
from orchestration import cli as orchestration_cli
from orchestration.cli import OrchestrationCliContext
from tests._helpers import assertions


@pytest.fixture(name="runner")
def _runner() -> CliRunner:
    return CliRunner()


def _read_envelope(path: Path) -> dict[str, object]:
    payload = path.read_text(encoding="utf-8")
    return cast("dict[str, object]", json.loads(payload))


def test_index_bm25_emits_success_envelope(
    tmp_path: Path,
    runner: CliRunner,
    orchestration_cli_context_builder: Callable[..., OrchestrationCliContext],
) -> None:
    """Test that index-bm25 command emits a success envelope with file artifacts."""
    def fake_build(
        config: orchestration_cli.BM25BuildConfig,
        logger: logging.Logger,
    ) -> tuple[str, int]:
        assertions.expect_true(
            isinstance(config, orchestration_cli.BM25BuildConfig),
            reason="config should be orchestration_cli.BM25BuildConfig",
        )
        assertions.expect_true(
            hasattr(logger, "info"),
            reason="logger should expose logging methods",
        )
        return "lucene", 3

    chunks_file = tmp_path / "chunks.jsonl"
    chunks_file.write_text("{}\n", encoding="utf-8")

    result = runner.invoke(
        orchestration_cli.app,
        [
            "--envelope-dir",
            str(tmp_path),
            "index-bm25",
            str(chunks_file),
            "--backend",
            "lucene",
            "--index-dir",
            str(tmp_path / "_indices" / "bm25"),
        ],
        obj={"orchestration_cli_context": orchestration_cli_context_builder(bm25_builder=fake_build)},
    )

    assertions.expect_equal(result.exit_code, 0)
    envelope_path = tmp_path / "kgf-orchestration-index-bm25.json"
    envelope = _read_envelope(envelope_path)
    assertions.expect_equal(envelope["status"], "success")
    files = cast("list[dict[str, object]]", envelope["files"])
    assertions.expect_true(
        any(cast("str", entry.get("path", "")).endswith("bm25_index") for entry in files),
        reason="should have bm25_index file",
    )


def test_index_faiss_records_validation_failure(
    tmp_path: Path,
    runner: CliRunner,
    orchestration_cli_context_builder: Callable[..., OrchestrationCliContext],
) -> None:
    """Test that index-faiss command records validation failures in error envelope."""
    error = VectorValidationError("invalid payload", errors=["row 1: missing vector"])

    def fake_run(*, config: orchestration_cli.IndexCliConfig) -> dict[str, object]:
        assertions.expect_true(
            isinstance(config, orchestration_cli.IndexCliConfig),
            reason="config should be orchestration_cli.IndexCliConfig",
        )
        raise error

    vectors_file = tmp_path / "vectors.json"
    vectors_file.write_text("[]", encoding="utf-8")

    result = runner.invoke(
        orchestration_cli.app,
        [
            "--envelope-dir",
            str(tmp_path),
            "index-faiss",
            str(vectors_file),
            "--index-path",
            str(tmp_path / "out.idx"),
        ],
        obj={
            "orchestration_cli_context": orchestration_cli_context_builder(
                faiss_runner=lambda config: fake_run(config=config)
            )
        },
    )

    assertions.expect_equal(result.exit_code, 1)
    envelope_path = tmp_path / "kgf-orchestration-index-faiss.json"
    envelope = _read_envelope(envelope_path)
    assertions.expect_equal(envelope["status"], "violation")
    problem = cast("dict[str, object]", envelope["problem"])
    assertions.expect_equal(
        problem["type"], "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
    )
    assertions.expect_equal(problem["vector_path"], str(vectors_file))
    assertions.expect_equal(problem["errors"], ["row 1: missing vector"])
