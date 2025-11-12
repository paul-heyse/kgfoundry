"""Offline hybrid evaluator with oracle reranking and pool exports."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from codeintel_rev.eval.pool_writer import PoolRow, Source, write_pool
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.io.xtr_manager import XTRIndex
else:  # pragma: no cover - imported lazily in CLI paths
    XTRIndex = object  # type: ignore[misc,assignment]

LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class EvalConfig:
    """Evaluator configuration."""

    pool_path: Path
    metrics_path: Path
    k: int = 10
    k_factor: float = 2.0
    nprobe: int | None = None
    max_queries: int | None = None
    use_xtr_oracle: bool = False


@dataclass(frozen=True)
class EvalReport:
    """Summary for an offline ANN vs oracle comparison."""

    queries: int
    k: int
    k_factor: float
    nprobe: int | None
    recall_at_k: float
    oracle_matches: int
    ann_hits: int
    xtr_records: int


@dataclass(slots=True, frozen=False)
class _EvalState:
    fetch_k: int
    search_k: int
    pool_rows: list[PoolRow]
    xtr_index: XTRIndex | None
    ann_hits: int = 0
    oracle_matches: int = 0
    xtr_rows: int = 0


class HybridPoolEvaluator:
    """Compare ANN retrieval against Flat and optional XTR oracles, persisting pools."""

    def __init__(
        self,
        catalog: DuckDBCatalog,
        manager: FAISSManager,
        *,
        xtr_index: XTRIndex | None = None,
    ) -> None:
        self._catalog = catalog
        self._manager = manager
        self._xtr_index = xtr_index
        self._text_cache: dict[int, str] = {}

    def run(self, config: EvalConfig) -> EvalReport:
        """Execute the evaluation and persist per-query pools + metrics.

        Returns
        -------
        EvalReport
            Structured summary containing query counts, recall, and oracle stats.
        """
        sample_limit = config.max_queries if config.max_queries is not None else 64
        queries = self._catalog.sample_query_vectors(limit=sample_limit)
        if not queries:
            LOGGER.warning("No query vectors available for evaluation.")
            empty_report = EvalReport(
                queries=0,
                k=config.k,
                k_factor=config.k_factor,
                nprobe=config.nprobe,
                recall_at_k=0.0,
                oracle_matches=0,
                ann_hits=0,
                xtr_records=0,
            )
            self._write_metrics(config.metrics_path, empty_report)
            write_pool([], config.pool_path)
            return empty_report

        pool_rows, ann_hits, oracle_matches, xtr_rows = self._evaluate_queries(queries, config)

        recall = oracle_matches / max(ann_hits, 1)
        config.pool_path.parent.mkdir(parents=True, exist_ok=True)
        write_pool(pool_rows, config.pool_path)

        report = EvalReport(
            queries=len(queries),
            k=max(config.k, 1),
            k_factor=config.k_factor,
            nprobe=config.nprobe,
            recall_at_k=recall,
            oracle_matches=oracle_matches,
            ann_hits=ann_hits,
            xtr_records=xtr_rows,
        )
        self._write_metrics(config.metrics_path, report)
        LOGGER.info(
            "Hybrid evaluation completed",
            extra={
                "queries": report.queries,
                "k": report.k,
                "k_factor": report.k_factor,
                "nprobe": report.nprobe,
                "recall_at_k": report.recall_at_k,
                "pool_rows": len(pool_rows),
                "pool_path": str(config.pool_path),
                "metrics_path": str(config.metrics_path),
                "xtr_records": report.xtr_records,
            },
        )
        return report

    def _evaluate_queries(
        self,
        queries: Sequence[tuple[int, np.ndarray]],
        config: EvalConfig,
    ) -> tuple[list[PoolRow], int, int, int]:
        state = self._build_eval_state(config)

        for query_id, raw_vec in queries:
            query_vec = np.asarray(raw_vec, dtype=np.float32).reshape(1, -1)
            ann_scores, ann_ids = self._manager.search(
                query_vec,
                k=state.search_k,
                nprobe=config.nprobe,
                catalog=self._catalog,
            )
            ann_ids_list = ann_ids[0].tolist()
            if not ann_ids_list:
                continue

            oracle_scores, oracle_ids = self._flat_rerank(query_vec, ann_ids_list, state.fetch_k)
            oracle_cut = oracle_ids[0].tolist()
            ann_cut = min(state.fetch_k, len(ann_ids_list))
            state.oracle_matches += len(
                set(ann_ids_list[:ann_cut]) & set(oracle_cut[: state.fetch_k])
            )
            state.ann_hits += ann_cut

            qid = str(query_id)
            self._extend_pool(
                state.pool_rows,
                query_id=qid,
                source="faiss",
                ids=ann_ids_list,
                scores=ann_scores[0].tolist(),
            )
            self._extend_pool(
                state.pool_rows,
                query_id=qid,
                source="oracle",
                ids=oracle_cut,
                scores=oracle_scores[0].tolist(),
            )

            if state.xtr_index is not None:
                text = self._get_query_text(int(query_id))
                xtr_ids, xtr_scores = self._score_with_xtr(text, ann_ids_list, state.fetch_k)
                if xtr_ids:
                    self._extend_pool(
                        state.pool_rows,
                        query_id=qid,
                        source="xtr",
                        ids=xtr_ids,
                        scores=xtr_scores,
                    )
                    state.xtr_rows += len(xtr_ids)

        return state.pool_rows, state.ann_hits, state.oracle_matches, state.xtr_rows

    def _build_eval_state(self, config: EvalConfig) -> _EvalState:
        fetch_k = max(config.k, 1)
        search_k = max(int(fetch_k * max(config.k_factor, 1.0)), fetch_k)
        xtr_index = (
            self._xtr_index
            if config.use_xtr_oracle
            and self._xtr_index
            and getattr(self._xtr_index, "ready", False)
            else None
        )
        if config.use_xtr_oracle and xtr_index is None:
            LOGGER.warning("Requested XTR oracle but index is unavailable or not ready.")
        return _EvalState(
            fetch_k=fetch_k,
            search_k=search_k,
            pool_rows=[],
            xtr_index=xtr_index,
        )

    def _flat_rerank(
        self,
        xq: np.ndarray,
        cand_ids: Sequence[int],
        topk: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not cand_ids:
            return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.int64)
        vectors = self._manager.reconstruct_batch(cand_ids)
        faiss = __import__("faiss")  # lazy import
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

    def _score_with_xtr(
        self,
        text: str | None,
        candidate_ids: Sequence[int],
        topk: int,
    ) -> tuple[list[int], list[float]]:
        if not text or not candidate_ids or not self._xtr_index:
            return ([], [])
        results = self._xtr_index.rescore(text, candidate_ids, explain=False)
        trimmed = results[:topk]
        ids = [chunk_id for chunk_id, _score, _payload in trimmed]
        scores = [float(score) for _, score, _ in trimmed]
        return ids, scores

    def _get_query_text(self, chunk_id: int) -> str | None:
        cached = self._text_cache.get(chunk_id)
        if cached is not None:
            return cached
        chunk = self._catalog.get_chunk_by_id(chunk_id)
        if not chunk:
            return None
        text = str(chunk.get("content") or chunk.get("preview") or "")
        self._text_cache[chunk_id] = text
        return text

    @staticmethod
    def _write_metrics(path: Path, report: EvalReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "queries": report.queries,
            "k": report.k,
            "k_factor": report.k_factor,
            "nprobe": report.nprobe,
            "recall_at_k": report.recall_at_k,
            "oracle_matches": report.oracle_matches,
            "ann_hits": report.ann_hits,
            "xtr_records": report.xtr_records,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = ["EvalConfig", "EvalReport", "HybridPoolEvaluator"]
