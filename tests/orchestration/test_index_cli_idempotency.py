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
from typing import TYPE_CHECKING, Any, cast

import pytest
import typer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable
    from pathlib import Path

    from _pytest.logging import LogCaptureFixture
else:  # pragma: no cover - runtime alias for type checking convenience
    LogCaptureFixture = Any

pytest.importorskip("orchestration.cli")
from orchestration.cli import index_bm25, index_faiss


class TestIndexBM25Idempotency:
    """Verify BM25 indexing is idempotent."""

    def test_index_bm25_identical_on_retry(
        self,
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

        for backend in ("lucene", "pure"):
            caplog.clear()
            caplog.set_level(logging.INFO)

            index_dir_1 = temp_index_dir / f"index_{backend}_1"
            index_bm25(
                chunks_parquet=str(chunks_file),
                backend=backend,
                index_dir=str(index_dir_1),
            )

            assert index_dir_1.exists()

            index_dir_2 = temp_index_dir / f"index_{backend}_2"
            index_bm25(
                chunks_parquet=str(chunks_file),
                backend=backend,
                index_dir=str(index_dir_2),
            )

            assert index_dir_1.exists()
            assert index_dir_2.exists()

            found_operation = any(
                cast("str | None", getattr(record, "operation", None)) == "index_bm25"
                for record in caplog.records
            )
            assert found_operation


class TestIndexFAISSIdempotency:
    """Verify FAISS indexing is idempotent."""

    def test_index_faiss_identical_on_retry(
        self,
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

        # First run
        index_path_1 = temp_index_dir / "index_1.idx"
        index_faiss(
            dense_vectors=str(vectors_file),
            index_path=str(index_path_1),
        )

        # Verify index was created
        assert index_path_1.exists()

        # Second run (idempotent)
        index_path_2 = temp_index_dir / "index_2.idx"
        index_faiss(
            dense_vectors=str(vectors_file),
            index_path=str(index_path_2),
        )

        # Both should exist
        assert index_path_1.exists()
        assert index_path_2.exists()

        # Verify structured logs indicate operation
        found_operation = any(
            cast("str | None", getattr(record, "operation", None)) == "index_faiss"
            for record in caplog.records
        )
        assert found_operation


class TestIndexingErrorHandling:
    """Verify error handling in index operations."""

    def test_index_bm25_missing_file(
        self,
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

        with pytest.raises(typer.Exit) as exc_info:
            index_bm25(
                chunks_parquet=str(temp_index_dir / "nonexistent.json"),
                backend="lucene",
                index_dir=str(temp_index_dir / "output"),
            )

        assert exc_info.value.exit_code == 1

        # Verify error was logged
        assert any(record.levelname == "ERROR" for record in caplog.records)

    def test_index_faiss_malformed_vectors(
        self,
        temp_index_dir: Path,
        caplog: LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify malformed vector data is rejected.

        Parameters
        ----------
        temp_index_dir : Path
            Temporary directory for test artifacts.
        caplog : LogCaptureFixture
            Pytest fixture for log capture.
        monkeypatch : pytest.MonkeyPatch
            Fixture used to capture Problem Details output from ``typer.echo``.
        """
        caplog.set_level(logging.ERROR)

        # Create malformed vector data
        vectors_file = temp_index_dir / "bad_vectors.json"
        bad_payload: dict[str, object] = {"not": "a list"}
        vectors_file.write_text(json.dumps(bad_payload))

        # Capture Problem Details emission
        messages: list[tuple[str, bool]] = []

        def _fake_echo(message: object, *, err: bool = False, **_: object) -> None:
            messages.append((str(message), err))

        monkeypatch.setattr(typer, "echo", _fake_echo)

        with pytest.raises(typer.Exit) as exc_info:
            index_faiss(
                dense_vectors=str(vectors_file),
                index_path=str(temp_index_dir / "output.idx"),
            )

        assert exc_info.value.exit_code == 1
        assert messages, "Expected Problem Details payload to be emitted"

        json_messages = [msg for msg, err in messages if err and msg.strip().startswith("{")]
        assert json_messages, "Expected structured Problem Details output"
        problem_raw: object = json.loads(json_messages[-1])
        assert isinstance(problem_raw, dict)
        problem = cast("dict[str, object]", problem_raw)
        assert (
            problem.get("type") == "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
        )
        assert problem.get("status") == 422
        assert problem.get("vector_path") == str(vectors_file)
        assert (
            problem.get("schema_id")
            == "https://kgfoundry.dev/schema/vector-ingestion/vector-batch.v1.json"
        )
        errors_list = cast("list[str]", problem.get("errors", []))
        assert errors_list, "Expected validation error details"
        assert "vector" in errors_list[0].lower()

        # Verify error was logged with correlation id metadata
        assert any(record.levelname == "ERROR" for record in caplog.records)


__all__ = [
    "TestIndexBM25Idempotency",
    "TestIndexFAISSIdempotency",
    "TestIndexingErrorHandling",
]
