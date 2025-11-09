"""CLI integration tests for vector ingestion."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from typer.testing import CliRunner

from orchestration.cli import app

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from uuid import UUID

    import pytest
    from _pytest.logging import LogCaptureFixture


def _filter_index_records(
    records: list[logging.LogRecord],
    *,
    level: str | None = None,
    message: str | None = None,
) -> list[logging.LogRecord]:
    """Return records emitted by the FAISS index operation.

    Parameters
    ----------
    records : list[logging.LogRecord]
        Log records to filter.
    level : str | None, optional
        Optional log level filter.
    message : str | None, optional
        Optional message filter.

    Returns
    -------
    list[logging.LogRecord]
        Filtered log records.
    """
    filtered: list[logging.LogRecord] = []
    for record in records:
        operation = cast("str | None", getattr(record, "operation", None))
        if operation != "index_faiss":
            continue
        if level is not None and record.levelname != level:
            continue
        if message is not None and record.getMessage() != message:
            continue
        filtered.append(record)
    return filtered


def _parse_problem(stderr: str) -> dict[str, object]:
    """Extract the Problem Details JSON object from CLI stderr.

    Parameters
    ----------
    stderr : str
        Standard error output from CLI.

    Returns
    -------
    dict[str, object]
        Parsed Problem Details dictionary.

    Raises
    ------
    AssertionError
        If Problem Details JSON not found in stderr.
    """
    lines = [line for line in stderr.splitlines() if line.strip()]
    json_line = next(
        (line for line in reversed(lines) if line.strip().startswith("{")), ""
    )
    if not json_line:
        msg = f"Expected Problem Details JSON, got: {stderr!r}"
        raise AssertionError(msg)

    problem_raw: object = json.loads(json_line)
    assert isinstance(problem_raw, dict)
    return cast("dict[str, object]", problem_raw)


def test_index_faiss_cli_success(
    tmp_path: Path,
    canonical_vector_payload: list[dict[str, object]],
    caplog: LogCaptureFixture,
) -> None:
    """Running the CLI with valid payloads should succeed and emit metrics."""
    runner = CliRunner()
    vectors_file = tmp_path / "vectors.json"
    vectors_file.write_text(json.dumps(canonical_vector_payload), encoding="utf-8")

    index_path = tmp_path / "faiss.idx"

    with caplog.at_level(logging.INFO, logger="orchestration.cli"):
        result = runner.invoke(
            app,
            [
                "index_faiss",
                str(vectors_file),
                "--index-path",
                str(index_path),
            ],
            mix_stderr=False,
        )

    assert result.exit_code == 0, result.output
    assert "FAISS index vectors stored" in result.stdout
    assert index_path.exists(), "Expected index artifact to be created"

    build_records = _filter_index_records(
        caplog.records, message="Building FAISS index"
    )
    assert build_records, "Expected structured build log with operation metadata"
    build_record = build_records[-1]
    vectors = cast("int | None", getattr(build_record, "vectors", None))
    dimension = cast("int | None", getattr(build_record, "dimension", None))
    correlation_id = cast("str | None", getattr(build_record, "correlation_id", None))
    assert vectors == 2
    assert dimension == 3
    assert correlation_id


def test_index_faiss_cli_problem_details(
    tmp_path: Path,
    deterministic_uuid_factory: Callable[[], UUID],
    caplog: LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid payloads should return RFC 9457 Problem Details envelopes."""
    monkeypatch.setattr("orchestration.cli.uuid4", deterministic_uuid_factory)

    vectors_path = tmp_path / "invalid_vectors.json"
    invalid_vectors: list[dict[str, object]] = [{"key": "", "vector": [0.1, 0.2]}]
    vectors_path.write_text(json.dumps(invalid_vectors), encoding="utf-8")

    index_path = tmp_path / "faiss-invalid.idx"

    with caplog.at_level(logging.ERROR, logger="orchestration.cli"):
        result = CliRunner().invoke(
            app,
            [
                "index_faiss",
                str(vectors_path),
                "--index-path",
                str(index_path),
            ],
            mix_stderr=False,
        )

    assert result.exit_code == 1
    assert not index_path.exists()

    stderr_text = result.stderr if result.stderr_bytes is not None else result.output
    problem = _parse_problem(stderr_text)
    assert (
        problem.get("type")
        == "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
    )
    assert problem.get("status") == 422
    validation_errors = cast("list[str]", problem.get("errors", []))
    assert validation_errors, "Expected validation error details"

    failure_records = _filter_index_records(caplog.records, level="ERROR")
    assert failure_records, "Expected error log with correlation metadata"
    failure_correlation = cast(
        "str | None", getattr(failure_records[-1], "correlation_id", None)
    )
    assert failure_correlation == "12345678123456781234567812345678"
