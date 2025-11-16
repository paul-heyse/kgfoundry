"""Tests for the hybrid evaluator orchestration."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import numpy as np
import pyarrow.parquet as pq
from codeintel_rev.eval.hybrid_evaluator import EvalConfig, HybridPoolEvaluator
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.xtr_manager import XTRIndex

from tests._helpers import assertions, constants


class _FakeCatalog:
    def __init__(self) -> None:
        self._queries = [
            (1, np.array([1.0, 0.0], dtype=np.float32)),
            (2, np.array([0.0, 1.0], dtype=np.float32)),
        ]

    def sample_query_vectors(self, limit: int = 64) -> list[tuple[int, np.ndarray]]:
        return self._queries[:limit]

    def get_chunk_by_id(self, chunk_id: int) -> dict[str, str]:
        # Access internal queries so Ruff treats this as a genuine instance method.
        vector_dims = len(self._queries[chunk_id % len(self._queries)][1])
        return {"content": f"chunk-{chunk_id}", "summary": f"{vector_dims}-dim"}

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, StructureAnnotations]:
        _ = len(self._queries)
        return {
            int(chunk_id): StructureAnnotations(
                uri=f"chunk-{chunk_id}",
                symbol_hits=("sym",),
                ast_node_kinds=("FunctionDef",),
                cst_matches=(),
            )
            for chunk_id in ids
        }


class _FakeManager:
    def __init__(self) -> None:
        self._vectors = {
            100: np.array([1.0, 0.0], dtype=np.float32),
            101: np.array([0.0, 1.0], dtype=np.float32),
        }

    def search(
        self,
        _query: np.ndarray,
        k: int,
        nprobe: int | None = None,
        catalog: object | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        available = list(self._vectors.keys())
        ids = np.array([available], dtype=np.int64)[:, :k]
        scores = np.array([[0.9, 0.1]], dtype=np.float32)[:, :k]
        _ = nprobe  # exercise signature parity
        _ = catalog
        return scores, ids

    def reconstruct_batch(self, ids: list[int] | np.ndarray) -> np.ndarray:
        return np.stack([self._vectors[int(i)] for i in ids], dtype=np.float32)


class _FakeXTRIndex:
    ready = True

    def __init__(self) -> None:
        self.rescore_calls = 0

    def rescore(
        self,
        _query: str,
        candidate_chunk_ids: Sequence[int],
        *,
        explain: bool = False,
    ) -> list[tuple[int, float, None]]:
        if not candidate_chunk_ids:
            return []
        self.rescore_calls += 1
        return [(candidate_chunk_ids[0], 2.0 if not explain else 1.5, None)]


class _UnsupportedOverrideError(ValueError):
    """Raised when _config receives unsupported keyword overrides."""

    def __init__(self, overrides: Sequence[str]) -> None:
        formatted = ", ".join(overrides)
        super().__init__(f"Unsupported overrides: {formatted}")


def _config(tmp_path: Path, **overrides: object) -> EvalConfig:
    pool_path = cast("Path", overrides.pop("pool_path", tmp_path / "pool.parquet"))
    metrics_path = cast("Path", overrides.pop("metrics_path", tmp_path / "metrics.json"))
    k = cast("int", overrides.pop("k", 1))
    k_factor = cast("float", overrides.pop("k_factor", 1.0))
    nprobe = cast("int | None", overrides.pop("nprobe", None))
    max_queries = cast("int | None", overrides.pop("max_queries", 2))
    use_xtr_oracle = cast("bool", overrides.pop("use_xtr_oracle", False))
    if overrides:
        unexpected = sorted(overrides)
        raise _UnsupportedOverrideError(unexpected)
    return EvalConfig(
        pool_path=pool_path,
        metrics_path=metrics_path,
        k=k,
        k_factor=k_factor,
        nprobe=nprobe,
        max_queries=max_queries,
        use_xtr_oracle=use_xtr_oracle,
    )


def test_hybrid_evaluator_writes_metrics(tmp_path: Path) -> None:
    """Evaluator writes pool+metrics artifacts and returns recall data."""
    evaluator = HybridPoolEvaluator(
        cast("DuckDBCatalog", _FakeCatalog()),
        cast("FAISSManager", _FakeManager()),
    )
    config = _config(tmp_path)
    report = evaluator.run(config)

    expected_queries = constants.BATCH_SIZES.minimal
    assertions.expect_equal(report.queries, expected_queries)
    assertions.expect_true(0.0 < report.recall_at_k <= 1.0)
    assertions.expect_true(config.pool_path.exists())
    table = pq.read_table(config.pool_path)
    assertions.expect_sequence_equal(
        sorted(set(table.column("channel").to_pylist())),
        ["faiss", "oracle"],
    )
    assertions.expect_in("symbol_hits", table.column_names)
    assertions.expect_true(
        all(isinstance(val, list) for val in table.column("symbol_hits").to_pylist())
    )
    assertions.expect_true(all(val for val in table.column("uri").to_pylist()))

    metrics = json.loads(config.metrics_path.read_text())
    assertions.expect_equal(metrics["recall_at_k"], report.recall_at_k)


def test_hybrid_evaluator_adds_xtr_rows(tmp_path: Path) -> None:
    """Evaluator emits XTR rows when oracle is enabled."""
    evaluator = HybridPoolEvaluator(
        cast("DuckDBCatalog", _FakeCatalog()),
        cast("FAISSManager", _FakeManager()),
        xtr_index=cast("XTRIndex", _FakeXTRIndex()),
    )
    config = _config(tmp_path, use_xtr_oracle=True)
    evaluator.run(config)
    table = pq.read_table(config.pool_path)
    assertions.expect_in("xtr", set(table.column("channel").to_pylist()))
