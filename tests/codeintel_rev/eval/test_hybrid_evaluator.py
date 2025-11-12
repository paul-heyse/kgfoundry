"""Tests for the hybrid evaluator orchestration."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from codeintel_rev.eval.hybrid_evaluator import EvalConfig, HybridPoolEvaluator


class _FakeCatalog:
    def __init__(self) -> None:
        self._queries = [
            (1, np.array([1.0, 0.0], dtype=np.float32)),
            (2, np.array([0.0, 1.0], dtype=np.float32)),
        ]

    def sample_query_vectors(self, limit: int = 64) -> list[tuple[int, np.ndarray]]:
        return self._queries[:limit]

    def get_chunk_by_id(self, chunk_id: int) -> dict[str, str]:
        return {"content": f"chunk-{chunk_id}"}


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
        _nprobe: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        ids = np.array([[100, 101]], dtype=np.int64)[:, :k]
        scores = np.array([[0.9, 0.1]], dtype=np.float32)[:, :k]
        return scores, ids

    def reconstruct_batch(self, ids: list[int] | np.ndarray) -> np.ndarray:
        return np.stack([self._vectors[int(i)] for i in ids], dtype=np.float32)


class _FakeXTRIndex:
    ready = True

    def rescore(
        self,
        _query: str,
        candidate_chunk_ids: Sequence[int],
        *,
        explain: bool = False,
    ) -> list[tuple[int, float, None]]:
        if not candidate_chunk_ids:
            return []
        return [(candidate_chunk_ids[0], 2.0 if not explain else 1.5, None)]


def _config(tmp_path: Path, **overrides: object) -> EvalConfig:
    defaults = {
        "pool_path": tmp_path / "pool.parquet",
        "metrics_path": tmp_path / "metrics.json",
        "k": 1,
        "k_factor": 1.0,
        "nprobe": None,
        "max_queries": 2,
        "use_xtr_oracle": False,
    }
    defaults.update(overrides)
    return EvalConfig(**defaults)


def test_hybrid_evaluator_writes_metrics(tmp_path: Path) -> None:
    evaluator = HybridPoolEvaluator(_FakeCatalog(), _FakeManager())
    config = _config(tmp_path)
    report = evaluator.run(config)

    assert report.queries == 2
    assert 0.0 < report.recall_at_k <= 1.0
    assert config.pool_path.exists()
    table = pq.read_table(config.pool_path)
    assert set(table.column("source").to_pylist()) == {"faiss", "oracle"}

    metrics = json.loads(config.metrics_path.read_text())
    assert metrics["recall_at_k"] == report.recall_at_k


def test_hybrid_evaluator_adds_xtr_rows(tmp_path: Path) -> None:
    evaluator = HybridPoolEvaluator(_FakeCatalog(), _FakeManager(), xtr_index=_FakeXTRIndex())
    config = _config(tmp_path, use_xtr_oracle=True)
    evaluator.run(config)
    table = pq.read_table(config.pool_path)
    assert "xtr" in set(table.column("source").to_pylist())
