"""Offline hybrid evaluator with oracle reranking and pool exports."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from codeintel_rev.eval.pool_writer import Channel, write_pool
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.faiss_store import reconstruct_batch as store_reconstruct_batch
from codeintel_rev.retrieval.types import SearchPoolRow

if TYPE_CHECKING:
    from codeintel_rev.io.xtr_manager import XTRIndex
else:  # pragma: no cover - imported lazily in CLI paths

    class XTRIndex:
        """Runtime placeholder for optional XTR dependency."""


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
    """Internal state tracking for hybrid evaluation execution.

    This dataclass maintains mutable state during evaluation, tracking search
    parameters, accumulated pool rows, and statistics. The state is updated
    incrementally as queries are evaluated, accumulating hits, matches, and
    pool rows for final reporting.

    Attributes
    ----------
    fetch_k : int
        Number of top results to fetch for oracle comparison. This is typically
        the evaluation k parameter, determining how many ANN results are compared
        against oracle rankings.
    search_k : int
        Number of results to retrieve from FAISS search. This is typically
        larger than fetch_k (by k_factor) to ensure sufficient candidates
        for oracle reranking.
    pool_rows : list[SearchPoolRow]
        Accumulated pool rows from all evaluated queries. Each row represents
        a retrieved document with its channel, rank, score, and reason metadata.
    xtr_index : XTRIndex | None
        Optional XTR index for oracle rescoring. If provided and enabled in
        config, XTR rescoring is performed on candidate results.
    ann_hits : int
        Total number of ANN (approximate nearest neighbor) hits accumulated
        across all queries. Incremented for each query's retrieved results.
    oracle_matches : int
        Total number of matches between ANN results and oracle rankings.
        Incremented when ANN results overlap with oracle top-k results.
    xtr_rows : int
        Total number of XTR-rescored results accumulated. Incremented when
        XTR oracle rescoring produces results for queries.
    """

    fetch_k: int
    search_k: int
    pool_rows: list[SearchPoolRow]
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
        self._structure_cache: dict[int, StructureAnnotations] = {}

    def run(self, config: EvalConfig) -> EvalReport:
        """Execute the evaluation and persist per-query pools + metrics.

        This method runs hybrid evaluation by sampling query vectors from the catalog,
        performing FAISS searches with the configured parameters, comparing results
        against brute-force and optional XTR oracles, and persisting evaluation
        artifacts (pool rows, metrics) to disk. The method computes recall metrics
        and generates an evaluation report.

        Parameters
        ----------
        config : EvalConfig
            Evaluation configuration containing search parameters (k, k_factor, nprobe),
            query limits (max_queries), and output paths (pool_path, metrics_path).
            The configuration determines how many queries to evaluate and where to
            persist results.

        Returns
        -------
        EvalReport
            Structured summary containing query counts, recall metrics, and oracle
            statistics. The report includes queries evaluated, recall_at_k, oracle_matches,
            ann_hits, and xtr_records. Returns an empty report if no query vectors
            are available.
        """
        sample_limit = config.max_queries if config.max_queries is not None else 64
        queries = self._catalog.sample_query_vectors(limit=sample_limit)
        if not queries:
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
        return report

    def _evaluate_queries(
        self,
        queries: Sequence[tuple[int, np.ndarray]],
        config: EvalConfig,
    ) -> tuple[list[SearchPoolRow], int, int, int]:
        """Evaluate a sequence of queries and accumulate pool rows and statistics.

        This method processes each query by performing FAISS search, comparing
        results against brute-force oracle reranking, and optionally applying
        XTR rescoring. For each query, pool rows are accumulated for all channels
        (FAISS, oracle, XTR), and statistics are tracked for recall computation.
        The method handles empty results gracefully and accumulates state across
        all queries.

        Parameters
        ----------
        queries : Sequence[tuple[int, np.ndarray]]
            Sequence of (query_id, query_vector) tuples to evaluate. Each query
            is processed independently, with results accumulated into the pool
            and statistics updated incrementally.
        config : EvalConfig
            Evaluation configuration containing search parameters (k, k_factor,
            nprobe) and XTR oracle settings. The configuration determines search
            depth and oracle selection.

        Returns
        -------
        tuple[list[SearchPoolRow], int, int, int]
            Tuple containing:
            - List of SearchPoolRow objects accumulated from all queries, with
              rows for FAISS, oracle, and optionally XTR channels.
            - Total ANN hits count across all queries.
            - Total oracle matches count (overlap between ANN and oracle top-k).
            - Total XTR rows count (if XTR oracle was used).

        Notes
        -----
        Query evaluation is the core of the hybrid evaluator, performing ANN
        search, oracle reranking, and optional XTR rescoring for each query.
        Results are accumulated incrementally, enabling efficient processing
        of large query sets. The method handles empty results and missing
        XTR index gracefully, ensuring robust evaluation even when optional
        components are unavailable.
        """
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
                channel="faiss",
                ids=ann_ids_list,
                scores=ann_scores[0].tolist(),
            )
            self._extend_pool(
                state.pool_rows,
                query_id=qid,
                channel="oracle",
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
                        channel="xtr",
                        ids=xtr_ids,
                        scores=xtr_scores,
                    )
                    state.xtr_rows += len(xtr_ids)

        return state.pool_rows, state.ann_hits, state.oracle_matches, state.xtr_rows

    def _build_eval_state(self, config: EvalConfig) -> _EvalState:
        """Initialize evaluation state from configuration.

        This method constructs an evaluation state object with search parameters
        computed from configuration. The state includes fetch_k (evaluation depth),
        search_k (FAISS retrieval depth), and optional XTR index if enabled.
        Search parameters are validated and normalized to ensure valid evaluation.

        Parameters
        ----------
        config : EvalConfig
            Evaluation configuration containing k, k_factor, and XTR oracle
            settings. The configuration determines search depths and oracle
            selection.

        Returns
        -------
        _EvalState
            Initialized evaluation state with search parameters computed from
            config and empty accumulators (pool_rows, statistics). The state
            is ready for incremental updates during query evaluation.

        Notes
        -----
        State initialization ensures consistent evaluation parameters across
        all queries. The fetch_k parameter determines evaluation depth, while
        search_k (computed as fetch_k * k_factor) ensures sufficient candidates
        for oracle reranking. XTR index is conditionally included based on
        configuration and availability.
        """
        fetch_k = max(config.k, 1)
        search_k = max(int(fetch_k * max(config.k_factor, 1.0)), fetch_k)
        xtr_index = (
            self._xtr_index
            if config.use_xtr_oracle
            and self._xtr_index
            and getattr(self._xtr_index, "ready", False)
            else None
        )
        return _EvalState(
            fetch_k=fetch_k,
            search_k=search_k,
            pool_rows=[],
            xtr_index=xtr_index,
        )

    def _ensure_structure_cache(self, chunk_ids: Sequence[int]) -> None:
        """Populate structure annotations for ``chunk_ids``."""
        missing = [cid for cid in chunk_ids if cid >= 0 and cid not in self._structure_cache]
        if not missing:
            return
        annotations = self._catalog.get_structure_annotations(missing)
        self._structure_cache.update(annotations)

    def _flat_rerank(
        self,
        xq: np.ndarray,
        cand_ids: Sequence[int],
        topk: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Perform brute-force reranking of candidates using exact similarity.

        This method implements oracle reranking by reconstructing candidate
        vectors from the FAISS index, normalizing both query and candidates,
        computing exact dot-product similarities, and returning top-k results
        sorted by score. This provides ground-truth rankings for comparison
        against approximate ANN results.

        Parameters
        ----------
        xq : np.ndarray
            Query vector of shape (1, dim) to rank candidates against. The
            vector is normalized before similarity computation.
        cand_ids : Sequence[int]
            Sequence of candidate chunk IDs to rerank. These IDs are used
            to reconstruct vectors from the FAISS index for exact similarity
            computation.
        topk : int
            Number of top-ranked results to return. The method returns the
            top-k candidates sorted by similarity score (highest first).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple containing:
            - Reranked similarity scores of shape (1, topk), sorted descending.
            - Reranked candidate IDs of shape (1, topk), corresponding to
              the sorted scores. Returns empty arrays if cand_ids is empty.

        Notes
        -----
        Oracle reranking provides ground-truth rankings by computing exact
        similarities between query and candidate vectors. This enables fair
        comparison of approximate ANN results against optimal rankings. The
        method uses L2 normalization and dot-product similarity, matching
        the FAISS index metric. Vector reconstruction from FAISS enables
        exact similarity computation without maintaining separate vector
        storage.
        """
        if not cand_ids:
            return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.int64)
        vectors = self._reconstruct_candidates(cand_ids)
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

    def _reconstruct_candidates(self, cand_ids: Sequence[int]) -> np.ndarray:
        """Return candidate vectors using store helpers or manager fallbacks.

        Returns
        -------
        np.ndarray
            Float32 array containing reconstructed vectors for ``cand_ids``.
        """
        reconstruct = getattr(self._manager, "reconstruct_batch", None)
        if callable(reconstruct):
            batch = reconstruct(list(cand_ids))
            return np.asarray(batch, dtype=np.float32)
        return store_reconstruct_batch(
            self._manager.require_cpu_index(),
            self._manager.vec_dim,
            cand_ids,
        )

    def _extend_pool(
        self,
        pool: list[SearchPoolRow],
        *,
        query_id: str,
        channel: Channel,
        ids: Sequence[int],
        scores: Sequence[float],
    ) -> None:
        """Add search results to the evaluation pool with structure metadata.

        This method converts search results (IDs and scores) into SearchPoolRow
        objects and appends them to the pool. Each row includes query ID, channel,
        rank, chunk ID, score, and reason metadata extracted from structure
        annotations. The method ensures structure annotations are cached before
        creating pool rows.

        Parameters
        ----------
        pool : list[SearchPoolRow]
            Pool list to extend with new search results. The list is modified
            in-place by appending SearchPoolRow objects.
        query_id : str
            Query identifier string uniquely identifying the query. Used to
            group pool rows by query across different channels.
        channel : Channel
            Channel name ("faiss", "oracle", "xtr") identifying the retrieval
            method that produced these results. Used to distinguish different
            ranking strategies in the pool.
        ids : Sequence[int]
            Sequence of chunk IDs from search results, ordered by relevance
            (highest score first). IDs are used to look up structure annotations
            and create pool rows.
        scores : Sequence[float]
            Sequence of relevance scores corresponding to ids, ordered by
            relevance (highest first). Scores are included in pool rows for
            analysis and comparison.

        Notes
        -----
        Pool extension enables structured evaluation by collecting all search
        results in a unified format. Structure annotations (symbol hits, AST
        kinds, CST matches) are included in reason metadata, enabling detailed
        analysis of why documents were retrieved. The method handles missing
        annotations gracefully by providing empty reason dictionaries.
        """
        self._ensure_structure_cache([int(chunk_id) for chunk_id in ids])
        for rank_idx, (chunk_id, score) in enumerate(zip(ids, scores, strict=True), start=1):
            chunk_key = int(chunk_id)
            info = self._structure_cache.get(chunk_key)
            reason = {
                "matched_symbols": list(info.symbol_hits) if info and info.symbol_hits else [],
                "ast_kind": info.ast_node_kinds[0] if info and info.ast_node_kinds else None,
                "cst_hits": list(info.cst_matches) if info and info.cst_matches else None,
            }
            pool.append(
                SearchPoolRow(
                    query_id=query_id,
                    channel=channel,
                    rank=rank_idx,
                    chunk_id=chunk_key,
                    score=float(score),
                    reason=reason,
                )
            )

    def _score_with_xtr(
        self,
        text: str | None,
        candidate_ids: Sequence[int],
        topk: int,
    ) -> tuple[list[int], list[float]]:
        """Rescore candidates using XTR index and return top-k results.

        This method applies XTR (cross-encoder) rescoring to candidate results,
        providing learned relevance scores based on query-candidate interactions.
        XTR rescoring improves ranking quality by considering query-candidate
        relationships beyond simple vector similarity. Results are trimmed to
        top-k and returned as separate ID and score lists.

        Parameters
        ----------
        text : str | None
            Query text string for XTR rescoring. If None or empty, returns
            empty results. The text is passed to XTR index for learned
            relevance scoring.
        candidate_ids : Sequence[int]
            Sequence of candidate chunk IDs to rescore. These IDs are passed
            to the XTR index along with query text for relevance computation.
        topk : int
            Maximum number of top-scored results to return. Results are sorted
            by XTR score (highest first) and trimmed to top-k.

        Returns
        -------
        tuple[list[int], list[float]]
            Tuple containing:
            - List of chunk IDs ranked by XTR score (highest first), trimmed
              to top-k. Returns empty list if text is None, candidates are
              empty, or XTR index is unavailable.
            - List of XTR relevance scores corresponding to the IDs, sorted
              descending. Returns empty list if no results are produced.

        Notes
        -----
        XTR rescoring enables learned relevance ranking by applying cross-encoder
        models that consider query-candidate interactions. This provides more
        accurate rankings than vector similarity alone, especially for semantic
        queries. The method handles missing XTR index gracefully by returning
        empty results, ensuring robust evaluation even when optional components
        are unavailable.
        """
        if not text or not candidate_ids or not self._xtr_index:
            return ([], [])
        results = self._xtr_index.rescore(text, candidate_ids, explain=False)
        trimmed = results[:topk]
        ids = [chunk_id for chunk_id, _score, _payload in trimmed]
        scores = [float(score) for _, score, _ in trimmed]
        return ids, scores

    def _get_query_text(self, chunk_id: int) -> str | None:
        """Retrieve query text for a chunk ID with caching.

        This method retrieves the text content of a chunk for use as query
        text in XTR rescoring. The method caches retrieved text to avoid
        repeated catalog lookups for the same chunk. Text is extracted from
        chunk content or preview fields, with empty string as fallback.

        Parameters
        ----------
        chunk_id : int
            Chunk identifier to retrieve text for. The chunk is looked up
            in the catalog, and its content or preview field is extracted.

        Returns
        -------
        str | None
            Query text string extracted from chunk content or preview, or
            None if chunk is not found in catalog. Empty string is returned
            if chunk exists but has no content or preview fields.

        Notes
        -----
        Query text retrieval enables XTR rescoring by providing natural language
        query text extracted from chunk content. Text caching improves performance
        by avoiding repeated catalog lookups for the same chunks. The method
        handles missing chunks gracefully by returning None, ensuring robust
        operation even when chunks are not available.
        """
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
        """Write evaluation metrics report to JSON file.

        This static method persists evaluation metrics to a JSON file for
        analysis and tracking. The metrics include query counts, recall
        statistics, and oracle comparison results. The file is written with
        pretty-printed JSON for readability.

        Parameters
        ----------
        path : Path
            File path where metrics should be written. The parent directory
            is created if it doesn't exist, ensuring the file can be written.
        report : EvalReport
            Evaluation report containing metrics to persist. The report
            includes queries evaluated, recall_at_k, oracle_matches, ann_hits,
            and xtr_records. All fields are serialized to JSON.

        Notes
        -----
        Metrics persistence enables tracking of evaluation results over time
        and comparison across different configurations. The JSON format enables
        easy parsing by analysis tools and integration with monitoring systems.
        The method ensures parent directories exist before writing to prevent
        errors.
        """
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
