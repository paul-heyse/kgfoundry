"""Tests for offline recall evaluation and query synthesis."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import numpy as np
from codeintel_rev.config.api import EvalSettings
from codeintel_rev.evaluation.offline_recall import OfflineRecallEvaluator
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow
from codeintel_rev.io.vllm_client import VLLMClient

from tests._helpers import assertions


class _StubFAISSManager:
    """Stub FAISS manager for testing offline evaluator."""

    def __init__(self, chunk_ids: list[int]) -> None:
        """Initialize stub manager with chunk IDs.

        Parameters
        ----------
        chunk_ids : list[int]
            Chunk IDs to return in search results.
        """
        self._chunk_ids = chunk_ids

    def search(
        self,
        query: np.ndarray,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: object | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return stub search results for test.

        Parameters
        ----------
        query : np.ndarray
            Query vector (unused).
        k : int | None, optional
            Number of results to return.
        nprobe : int | None, optional
            Nprobe parameter (unused).
        runtime : object | None, optional
            Runtime object (unused).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple of distance and ID arrays.
        """
        del query, nprobe, runtime
        k = k or len(self._chunk_ids)
        hits = self._chunk_ids[:k]
        distances = np.ones((1, len(hits)), dtype=np.float32)
        ids = np.array([hits], dtype=np.int64)
        return distances, ids


class _StubVLLMClient:
    """Stub VLLM client for testing offline evaluator."""

    def __init__(self, dim: int) -> None:
        """Initialize stub client with embedding dimension.

        Parameters
        ----------
        dim : int
            Embedding dimension.
        """
        self._dim = dim

    def embed_single(self, text: str) -> list[float]:
        """Return stub embedding vector for test.

        Parameters
        ----------
        text : str
            Text to embed (must be non-empty).

        Returns
        -------
        list[float]
            Zero-filled embedding vector of configured dimension.
        """
        assertions.expect_true(bool(text), reason="text should be non-empty")
        return [0.0] * self._dim


def _prepare_symbol_catalog(db_path: Path) -> DuckDBManager:
    """Prepare symbol catalog database with test data.

    Parameters
    ----------
    db_path : Path
        Database file path.

    Returns
    -------
    DuckDBManager
        Manager instance with test symbol data loaded.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    manager = DuckDBManager(db_path)
    catalog = SymbolCatalog(manager)
    catalog.ensure_schema()
    row = SymbolDefRow(
        symbol="python://pkg#func",
        display_name="func",
        kind="function",
        language="python",
        uri="src/pkg.py",
        start_line=1,
        start_col=0,
        end_line=5,
        end_col=1,
        chunk_id=101,
    )
    with manager.connection() as conn:
        conn.execute(
            """
            INSERT INTO symbol_defs(
              symbol, display_name, kind, language, uri,
              start_line, start_col, end_line, end_col, chunk_id, docstring, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.symbol,
                row.display_name,
                row.kind,
                row.language,
                row.uri,
                row.start_line,
                row.start_col,
                row.end_line,
                row.end_col,
                row.chunk_id,
                row.docstring,
                row.signature,
            ),
        )
    return manager


def test_offline_eval_synthesizes_queries(tmp_path: Path) -> None:
    """Test that offline evaluator synthesizes queries from symbol catalog."""
    repo_root = tmp_path / "repo"
    duckdb_path = repo_root / "catalog.duckdb"
    duckdb_manager = _prepare_symbol_catalog(duckdb_path)
    eval_settings = EvalSettings(
        enabled=True,
        output_dir=repo_root / "artifacts",
        k_values=(5,),
    )
    evaluator = OfflineRecallEvaluator(
        eval_settings=eval_settings,
        repo_root=repo_root,
        faiss_manager=cast("FAISSManager", _StubFAISSManager([101, 202])),
        vllm_client=cast("VLLMClient", _StubVLLMClient(2)),
        duckdb_manager=duckdb_manager,
    )
    result = evaluator.run()
    assertions.expect_equal(result["queries"], 1)
    summary = cast("Mapping[int, float]", result["summary"])
    assertions.expect_almost_equal(summary[5], 1.0)
    summary_path = repo_root / "artifacts" / "summary.json"
    assertions.expect_true(summary_path.exists(), reason="summary_path should exist")
