"""Offline hybrid evaluator with oracle reranking and pool exports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from codeintel_rev.eval.pool_writer import PoolRow, Source, write_pool
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class EvalReport:
    """Summary for an offline ANN vs oracle comparison."""

    queries: int
    k: int
    k_factor: float
    recall_at_k: float


class HybridPoolEvaluator:
    """Compare ANN retrieval against a Flat oracle and persist pools."""

    def __init__(self, catalog: DuckDBCatalog, manager: FAISSManager) -> None:
        self._catalog = catalog
        self._manager = manager

    def _flat_rerank(
        self,
        xq: np.ndarray,
        cand_ids: Sequence[int],
        topk: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Run Flat rerank over candidate IDs returned by ANN search.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Oracle scores and IDs ordered by cosine similarity.
        """
        if not cand_ids:
            return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.int64)
        vectors = self._manager.reconstruct_batch(cand_ids)
        faiss = __import__("faiss")  # lazy import to avoid startup cost
        faiss.normalize_L2(vectors)
        query = xq.copy()
        faiss.normalize_L2(query)
        scores = query @ vectors.T
        order = np.argsort(-scores, axis=1)[:, :topk]
        idx = np.asarray(cand_ids, dtype=np.int64)
        reranked_ids = np.take_along_axis(idx.reshape(1, -1), order, axis=1)
        reranked_scores = np.take_along_axis(scores, order, axis=1)
        return reranked_scores, reranked_ids

    @staticmethod
    def _extend_pool(
        pool: list[PoolRow],
        *,
        query_id: str,
        source: Source,
        ids: Sequence[int],
        scores: Sequence[float],
    ) -> None:
        """Append pool rows for a single query/source pair."""
        for rank_idx, (chunk_id, score) in enumerate(zip(ids, scores, strict=True), start=1):
            pool.append(
                PoolRow(
                    query_id=query_id,
                    source=source,
                    rank=rank_idx,
                    chunk_id=int(chunk_id),
                    score=float(score),
                )
            )

    def run(self, *, k: int, k_factor: float, out_parquet: Path | None = None) -> dict[str, object]:
        """Execute the evaluation and optionally persist per-query pools.

        Returns
        -------
        dict[str, object]
            JSON-serializable report with query count and recall@k.
        """
        queries = self._catalog.sample_query_vectors()
        if not queries:
            LOGGER.warning("No query vectors available for evaluation.")
            return EvalReport(queries=0, k=k, k_factor=k_factor, recall_at_k=0.0).__dict__

        ann_hits = 0
        oracle_matches = 0
        pool_rows: list[PoolRow] = []
        fetch_k = max(k, 1)
        search_k = max(int(fetch_k * max(k_factor, 1.0)), fetch_k)

        for query_id, raw_vec in queries:
            query_vec = np.asarray(raw_vec, dtype=np.float32).reshape(1, -1)
            ann_scores, ann_ids = self._manager.search(query_vec, k=search_k)
            ann_scores = ann_scores[0]
            ann_ids = ann_ids[0].tolist()
            if not ann_ids:
                continue

            oracle_scores, oracle_ids = self._flat_rerank(query_vec, ann_ids, fetch_k)
            oracle_scores = oracle_scores[0]
            oracle_ids = oracle_ids[0].tolist()

            ann_cut = min(fetch_k, len(ann_ids))
            oracle_matches += len(set(ann_ids[:ann_cut]) & set(oracle_ids[:fetch_k]))
            ann_hits += ann_cut

            qid = str(query_id)
            self._extend_pool(pool_rows, query_id=qid, source="faiss", ids=ann_ids, scores=ann_scores)
            self._extend_pool(
                pool_rows,
                query_id=qid,
                source="oracle",
                ids=oracle_ids,
                scores=oracle_scores,
            )

        recall = oracle_matches / max(ann_hits, 1)
        if out_parquet is not None:
            write_pool(pool_rows, out_parquet)

        report = EvalReport(
            queries=len(queries),
            k=fetch_k,
            k_factor=k_factor,
            recall_at_k=recall,
        )
        LOGGER.info(
            "Hybrid evaluation completed",
            extra={
                "queries": report.queries,
                "k": report.k,
                "k_factor": report.k_factor,
                "recall_at_k": report.recall_at_k,
                "pool_rows": len(pool_rows),
                "output": str(out_parquet) if out_parquet else None,
            },
        )
        return report.__dict__


__all__ = ["EvalReport", "HybridPoolEvaluator"]
