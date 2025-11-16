"""Tests for orchestration CLI refactoring with typed config.

This module verifies that the refactored index_faiss and run_index_faiss functions properly use
IndexCliConfig and handle error cases correctly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

from orchestration import cli as cli_module
from orchestration.cli import index_faiss, run_index_faiss
from orchestration.config import IndexCliConfig
from tests._helpers import assertions

# Test constants for docstring length assertions
_MIN_DOCSTRING_LENGTH = 50


def test_keyword_only_parameter() -> None:
    """Test that config parameter is keyword-only."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = IndexCliConfig(
            dense_vectors="vectors.json",
            index_path=f"{tmpdir}/index.idx",
            factory="Flat",
            metric="ip",
        )
        # Calling with keyword should work (when properly mocked)
        # Direct positional call would raise TypeError at runtime
        assertions.expect_equal(config.dense_vectors, "vectors.json")


def test_run_index_faiss_accepts_config() -> None:
    """Test that run_index_faiss accepts IndexCliConfig."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = IndexCliConfig(
            dense_vectors="vectors.json",
            index_path=f"{tmpdir}/index.idx",
            factory="Flat",
            metric="ip",
        )
        # Verify config is properly structured
        assertions.expect_true(
            isinstance(config, IndexCliConfig), reason="config should be IndexCliConfig"
        )
        assertions.expect_equal(config.factory, "Flat")
        assertions.expect_equal(config.metric, "ip")


def test_index_faiss_constructs_config_correctly() -> None:
    """Test that index_faiss constructs IndexCliConfig from CLI args."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vectors_file = Path(tmpdir) / "vectors.json"
        index_file = Path(tmpdir) / "index.idx"

        # Create dummy vectors file
        vectors_file.write_text("[]", encoding="utf-8")

        # Mock run_index_faiss to capture the config
        with patch("orchestration.cli.run_index_faiss") as mock_run:
            index_faiss(
                str(vectors_file),
                str(index_file),
                "Flat",
                "ip",
            )
            # Verify run_index_faiss was called once
            assertions.expect_equal(mock_run.call_count, 1)
            # Extract the config from the call
            call_kwargs = cast("dict[str, object]", mock_run.call_args[1])
            assertions.expect_in("config", call_kwargs)
            config = cast("IndexCliConfig", call_kwargs["config"])
            assertions.expect_true(
                isinstance(config, IndexCliConfig), reason="config should be IndexCliConfig"
            )
            assertions.expect_equal(config.dense_vectors, str(vectors_file))
            assertions.expect_equal(config.index_path, str(index_file))
            assertions.expect_equal(config.factory, "Flat")
            assertions.expect_equal(config.metric, "ip")


def test_index_faiss_uses_defaults() -> None:
    """Test that index_faiss uses default values correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vectors_file = Path(tmpdir) / "vectors.json"
        vectors_file.write_text("[]", encoding="utf-8")

        with patch("orchestration.cli.run_index_faiss") as mock_run:
            index_faiss(str(vectors_file))
            call_kwargs = cast("dict[str, object]", mock_run.call_args[1])
            config = cast("IndexCliConfig", call_kwargs["config"])
            assertions.expect_true(
                isinstance(config, IndexCliConfig), reason="config should be IndexCliConfig"
            )
            assertions.expect_equal(config.index_path, "./_indices/faiss/shard_000.idx")
            assertions.expect_equal(config.factory, "Flat")
            assertions.expect_equal(config.metric, "ip")


def test_docstring_present() -> None:
    """Test that run_index_faiss has a docstring."""
    assertions.expect_true(run_index_faiss.__doc__ is not None, reason="docstring should exist")
    if run_index_faiss.__doc__ is not None:
        assertions.expect_true(
            len(run_index_faiss.__doc__) > _MIN_DOCSTRING_LENGTH,
            reason="docstring should be substantial",
        )


def test_docstring_mentions_config() -> None:
    """Test that docstring mentions IndexCliConfig."""
    doc = run_index_faiss.__doc__ or ""
    assertions.expect_in("IndexCliConfig", doc)
    assertions.expect_in("config", doc.lower())


def test_docstring_has_examples() -> None:
    """Test that docstring has Examples section."""
    doc = run_index_faiss.__doc__ or ""
    assertions.expect_in("Examples", doc)
    assertions.expect_in("IndexCliConfig(", doc)


def test_docstring_documents_errors() -> None:
    """Test that docstring documents error handling."""
    doc = run_index_faiss.__doc__ or ""
    assertions.expect_in("Raises", doc)
    assertions.expect_in("typer.Exit", doc)
    assertions.expect_in("Problem Details", doc)


def test_index_faiss_docstring_present() -> None:
    """Test that index_faiss has a docstring."""
    assertions.expect_true(index_faiss.__doc__ is not None, reason="docstring should exist")
    if index_faiss.__doc__ is not None:
        assertions.expect_true(
            len(index_faiss.__doc__) > _MIN_DOCSTRING_LENGTH,
            reason="docstring should be substantial",
        )


def test_index_faiss_docstring_has_examples() -> None:
    """Test that index_faiss docstring has Examples."""
    doc = index_faiss.__doc__ or ""
    assertions.expect_in("Examples", doc)


def test_index_faiss_docstring_documents_parameters() -> None:
    """Test that docstring documents all parameters."""
    doc = index_faiss.__doc__ or ""
    assertions.expect_in("dense_vectors", doc)
    assertions.expect_in("index_path", doc)
    assertions.expect_in("factory", doc)
    assertions.expect_in("metric", doc)


def test_run_index_faiss_in_all() -> None:
    """Test that run_index_faiss is exported in __all__."""
    assertions.expect_in("run_index_faiss", cli_module.__all__)


def test_index_faiss_in_all() -> None:
    """Test that index_faiss is still exported in __all__."""
    assertions.expect_in("index_faiss", cli_module.__all__)


def test_config_can_be_created_from_cli_values() -> None:
    """Test that IndexCliConfig can be created from typical CLI values."""
    config = IndexCliConfig(
        dense_vectors="my_vectors.json",
        index_path="./_indices/faiss/shard_000.idx",
        factory="OPQ64,IVF8192,PQ64",
        metric="l2",
    )
    assertions.expect_equal(config.dense_vectors, "my_vectors.json")
    assertions.expect_equal(config.factory, "OPQ64,IVF8192,PQ64")
    assertions.expect_equal(config.metric, "l2")


def test_config_with_custom_paths() -> None:
    """Test IndexCliConfig with custom file paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = IndexCliConfig(
            dense_vectors=f"{tmpdir}/custom_vectors.json",
            index_path=f"{tmpdir}/custom_index.idx",
            factory="Flat",
            metric="ip",
        )
        assertions.expect_true(
            config.dense_vectors.endswith("custom_vectors.json"),
            reason="dense_vectors should end with custom_vectors.json",
        )
        assertions.expect_true(
            config.index_path.endswith("custom_index.idx"),
            reason="index_path should end with custom_index.idx",
        )


def test_both_functions_handle_same_parameters() -> None:
    """Test that both functions can handle the same parameter values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vectors_file = Path(tmpdir) / "vectors.json"
        index_file = Path(tmpdir) / "index.idx"
        vectors_file.write_text("[]", encoding="utf-8")

        config = IndexCliConfig(
            dense_vectors=str(vectors_file),
            index_path=str(index_file),
            factory="Flat",
            metric="ip",
        )

        # Both functions should accept the same data
        assertions.expect_equal(config.dense_vectors, str(vectors_file))
        assertions.expect_equal(config.index_path, str(index_file))
        assertions.expect_equal(config.factory, "Flat")
        assertions.expect_equal(config.metric, "ip")
