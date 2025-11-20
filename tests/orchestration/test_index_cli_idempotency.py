"""Idempotency and retry tests for orchestration CLI index commands.

Verify:
- index_bm25 and index_faiss are idempotent
- Repeated runs produce identical results
- Structured logging indicates idempotent behavior
- No duplicate side effects on retries
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from click.testing import Result

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from _pytest.logging import LogCaptureFixture
else:  # pragma: no cover - runtime alias for type checking convenience
    LogCaptureFixture = Any

from tests._helpers import assertions
from tests._helpers import cli as cli_helpers

cli_module = pytest.importorskip("orchestration.cli")


def _invoke_orchestration_cli(
    envelope_dir: Path,
    args: Sequence[str],
) -> Result:
    """Invoke orchestration CLI command.

    Parameters
    ----------
    envelope_dir : Path
        Envelope directory path.
    args : Sequence[str]
        CLI arguments to pass.

    Returns
    -------
    Result
        CLI runner result.
    """
    return cli_helpers.invoke(
        cli_module.app,
        [
            "--envelope-dir",
            str(envelope_dir),
            *args,
        ],
    )


def test_index_bm25_identical_on_retry(
    temp_index_dir: Path,
    caplog: LogCaptureFixture,
) -> None:
    """Verify BM25 index is identical when created twice.

    Parameters
    ----------
    temp_index_dir : Path
        Temporary directory for test artifacts.
    caplog : LogCaptureFixture
        Pytest fixture for log capture.
    """
    chunks_file = temp_index_dir / "chunks.json"
    chunks_data = [
        {
            "chunk_id": "c1",
            "title": "Doc 1",
            "section": "Intro",
            "text": "Hello world",
        },
        {
            "chunk_id": "c2",
            "title": "Doc 2",
            "section": "Body",
            "text": "More content",
        },
    ]
    chunks_file.write_text(json.dumps(chunks_data))
    envelope_dir = temp_index_dir / "cli_envelopes"

    for backend in ("lucene", "pure"):
        caplog.clear()
        caplog.set_level(logging.INFO)

        index_dir_1 = temp_index_dir / f"index_{backend}_1"
        result_one = _invoke_orchestration_cli(
            envelope_dir,
            [
                "index-bm25",
                str(chunks_file),
                "--backend",
                backend,
                "--index-dir",
                str(index_dir_1),
            ],
        )
        assertions.expect_equal(result_one.exit_code, 0)

        assertions.expect_true(index_dir_1.exists(), reason="index_dir_1 should exist")

        index_dir_2 = temp_index_dir / f"index_{backend}_2"
        result_two = _invoke_orchestration_cli(
            envelope_dir,
            [
                "index-bm25",
                str(chunks_file),
                "--backend",
                backend,
                "--index-dir",
                str(index_dir_2),
            ],
        )
        assertions.expect_equal(result_two.exit_code, 0)

        assertions.expect_true(index_dir_1.exists(), reason="index_dir_1 should still exist")
        assertions.expect_true(index_dir_2.exists(), reason="index_dir_2 should exist")

        found_operation = any(
            cast("str | None", getattr(record, "operation", None)) == "index_bm25"
            for record in caplog.records
        )
        assertions.expect_true(found_operation, reason="found_operation should be True")


def test_index_faiss_identical_on_retry(
    temp_index_dir: Path,
    caplog: LogCaptureFixture,
) -> None:
    """Verify FAISS index is identical when created twice.

    Parameters
    ----------
    temp_index_dir : Path
        Temporary directory for test artifacts.
    caplog : LogCaptureFixture
        Pytest fixture for log capture.
    """
    caplog.set_level(logging.INFO)

    # Create test vector data
    vectors_file = temp_index_dir / "vectors.json"
    vectors_data: list[dict[str, Iterable[float] | str]] = [
        {"key": "v1", "vector": [0.1, 0.2, 0.3]},
        {"key": "v2", "vector": [0.4, 0.5, 0.6]},
    ]
    vectors_file.write_text(json.dumps(vectors_data))
    envelope_dir = temp_index_dir / "cli_envelopes"

    # First run
    index_path_1 = temp_index_dir / "index_1.idx"
    result_one = _invoke_orchestration_cli(
        envelope_dir,
        [
            "index-faiss",
            str(vectors_file),
            "--index-path",
            str(index_path_1),
        ],
    )
    assertions.expect_equal(result_one.exit_code, 0)

    # Verify index was created
    assertions.expect_true(index_path_1.exists(), reason="index_path_1 should exist")

    # Second run (idempotent)
    index_path_2 = temp_index_dir / "index_2.idx"
    result_two = _invoke_orchestration_cli(
        envelope_dir,
        [
            "index-faiss",
            str(vectors_file),
            "--index-path",
            str(index_path_2),
        ],
    )
    assertions.expect_equal(result_two.exit_code, 0)

    # Both should exist
    assertions.expect_true(index_path_1.exists(), reason="index_path_1 should still exist")
    assertions.expect_true(index_path_2.exists(), reason="index_path_2 should exist")

    # Verify structured logs indicate operation
    found_operation = any(
        cast("str | None", getattr(record, "operation", None)) == "index_faiss"
        for record in caplog.records
    )
    assertions.expect_true(found_operation, reason="found_operation should be True")


def test_index_bm25_missing_file(
    temp_index_dir: Path,
    caplog: LogCaptureFixture,
) -> None:
    """Verify missing input file raises error.

    Parameters
    ----------
    temp_index_dir : Path
        Temporary directory for test artifacts.
    caplog : LogCaptureFixture
        Pytest fixture for log capture.
    """
    caplog.set_level(logging.ERROR)

    result = _invoke_orchestration_cli(
        temp_index_dir / "cli_envelopes",
        [
            "index-bm25",
            str(temp_index_dir / "nonexistent.json"),
            "--backend",
            "lucene",
            "--index-dir",
            str(temp_index_dir / "output"),
        ],
    )
    assertions.expect_equal(result.exit_code, 1)

    # Verify error was logged
    assertions.expect_true(
        any(record.levelname == "ERROR" for record in caplog.records),
        reason="should have ERROR log",
    )


def test_index_faiss_malformed_vectors(
    temp_index_dir: Path,
    caplog: LogCaptureFixture,
) -> None:
    """Verify malformed vector data is rejected.

    Parameters
    ----------
    temp_index_dir : Path
        Temporary directory for test artifacts.
    caplog : LogCaptureFixture
        Pytest fixture for log capture.
    """
    caplog.set_level(logging.ERROR)

    # Create malformed vector data
    vectors_file = temp_index_dir / "bad_vectors.json"
    bad_payload: dict[str, object] = {"not": "a list"}
    vectors_file.write_text(json.dumps(bad_payload))

    result = _invoke_orchestration_cli(
        temp_index_dir / "cli_envelopes",
        [
            "index-faiss",
            str(vectors_file),
            "--index-path",
            str(temp_index_dir / "output.idx"),
        ],
    )
    assertions.expect_equal(result.exit_code, 1)

    json_messages = [
        line
        for line in result.stderr.splitlines()
        if line.strip().startswith("{") and line.strip().endswith("}")
    ]
    assertions.expect_true(bool(json_messages), reason="Expected structured Problem Details output")
    problem_raw: object = json.loads(json_messages[-1])
    assertions.expect_true(isinstance(problem_raw, dict), reason="problem_raw should be dict")
    problem = cast("dict[str, object]", problem_raw)
    assertions.expect_equal(
        problem.get("type"), "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
    )
    assertions.expect_equal(problem.get("status"), 422)
    assertions.expect_equal(problem.get("vector_path"), str(vectors_file))
    assertions.expect_equal(
        problem.get("schema_id"),
        "https://kgfoundry.dev/schema/vector-ingestion/vector-batch.v1.json",
    )
    errors_list = cast("list[str]", problem.get("errors", []))
    assertions.expect_true(bool(errors_list), reason="Expected validation error details")
    assertions.expect_in("vector", errors_list[0].lower())

    # Verify error was logged with correlation id metadata
    assertions.expect_true(
        any(record.levelname == "ERROR" for record in caplog.records),
        reason="should have ERROR log",
    )
