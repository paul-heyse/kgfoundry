"""Tests for SCIP coverage evaluation and metrics reporting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from codeintel_rev.evaluation.scip_coverage import SCIPCoverageEvaluator
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow

from tests._helpers import assertions


class _StubFaissManager:
    """Stub satisfying the SupportsFaissSearch protocol."""

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
            Tuple of distance and ID arrays with stub values.
        """
        del self, query, nprobe, runtime
        result_k = max(1, int(k or 1))
        ids = np.full((1, result_k), 101, dtype=np.int64)
        distances = np.full((1, result_k), 0.9, dtype=np.float32)
        return distances, ids


class _StubVLLMClient:
    """Stub satisfying SupportsEmbedSingle."""

    def embed_single(self, text: str) -> list[float]:
        """Return stub embedding vector for test.

        Parameters
        ----------
        text : str
            Text to embed (must be non-empty).

        Returns
        -------
        list[float]
            Zero-filled embedding vector [0.0, 0.0].
        """
        del self
        assertions.expect_true(bool(text), reason="text should be non-empty")
        return [0.0, 0.0]


def _create_stub_faiss_manager() -> _StubFaissManager:
    """Create stub FAISS manager for testing.

    Returns
    -------
    _StubFaissManager
        Stub manager instance.
    """
    return _StubFaissManager()


def _create_stub_vllm_client() -> _StubVLLMClient:
    """Create stub VLLM client for testing.

    Returns
    -------
    _StubVLLMClient
        Stub client instance.
    """
    return _StubVLLMClient()


def _prepare_catalog(path: Path) -> DuckDBManager:
    """Prepare symbol catalog database with test data.

    Parameters
    ----------
    path : Path
        Database file path.

    Returns
    -------
    DuckDBManager
        Manager instance with test symbol data loaded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    manager = DuckDBManager(path)
    catalog = SymbolCatalog(manager)
    catalog.ensure_schema()
    with manager.connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO chunks(id) VALUES (101)")
    catalog.upsert_symbol_defs(
        [
            SymbolDefRow(
                symbol="python://pkg#func",
                display_name="func",
                kind="function",
                language="python",
                uri="src/pkg.py",
                start_line=1,
                start_col=0,
                end_line=3,
                end_col=1,
                chunk_id=101,
            )
        ]
    )
    return manager


def test_scip_coverage_reports_full_metrics(tmp_path: Path) -> None:
    """Test that SCIP coverage evaluator reports full coverage metrics."""
    repo_root = tmp_path / "repo"
    duckdb_path = repo_root / "catalog.duckdb"
    duckdb_manager = _prepare_catalog(duckdb_path)
    evaluator = SCIPCoverageEvaluator(
        repo_root=repo_root,
        duckdb_manager=duckdb_manager,
        faiss_manager=_create_stub_faiss_manager(),
        vllm_client=_create_stub_vllm_client(),
        default_output_dir=repo_root / "artifacts",
    )
    summary = evaluator.run(k=5)
    assertions.expect_equal(summary["chunk_coverage"], 1.0)
    assertions.expect_equal(summary["index_coverage"], 1.0)
    assertions.expect_equal(summary["retrieval_coverage"], 1.0)
