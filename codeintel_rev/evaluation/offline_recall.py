"""Offline recall evaluator leveraging FAISS + DuckDB catalogs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from codeintel_rev.config.settings import EvalConfig, PathsConfig, Settings
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.metrics.registry import (
    OFFLINE_EVAL_QUERY_COUNT,
    OFFLINE_EVAL_RECALL_AT_K,
)
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ResolvedPaths

LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class EvalQuery:
    """Single offline evaluation query with known positives."""

    qid: str
    text: str
    positives: tuple[int, ...]
    metadata: dict[str, object] | None = None


class OfflineRecallEvaluator:
    """Compute recall@K for FAISS retrieval using curated or synthesized queries."""

    def __init__(
        self,
        *,
        settings: Settings,
        paths: PathsConfig | ResolvedPaths,
        faiss_manager: FAISSManager,
        vllm_client: VLLMClient,
        duckdb_manager: DuckDBManager,
    ) -> None:
        self._settings = settings
        self._repo_root = Path(paths.repo_root)
        self._faiss = faiss_manager
        self._vllm = vllm_client
        self._symbol_catalog = SymbolCatalog(duckdb_manager)

    def run(
        self,
        *,
        queries_path: Path | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, object]:
        """Execute offline evaluation and persist artifacts.

        Extended Summary
        ----------------
        This method runs offline recall evaluation by loading queries (from file
        or synthesizing from symbol catalog), performing FAISS searches for each
        query, computing recall metrics at multiple k values against ground truth
        (symbol definitions), and persisting evaluation artifacts (per-query results,
        aggregate recall statistics) to the output directory. Used for validating
        index quality and tuning search parameters.

        Parameters
        ----------
        queries_path : Path | None, optional
            Path to JSONL file containing queries ({qid, text, positives}). If None,
            queries are synthesized from symbol catalog using configured strategy.
        output_dir : Path | None, optional
            Directory for evaluation artifacts (per-query results, aggregate stats).
            If None, uses `settings.eval.output_dir`.

        Returns
        -------
        dict[str, object]
            Dictionary containing:
            - "queries": int, number of queries evaluated
            - "summary": dict[int, float], aggregate recall at each k value
            Returns {"queries": 0, "summary": {}} if no queries available.

        Notes
        -----
        This method performs offline evaluation by iterating over queries and
        computing recall metrics. Evaluation artifacts are written to the output
        directory for analysis. Time complexity: O(n_queries * search_time) where
        search_time depends on index size and k values.
        """
        cfg = self._settings.eval
        k_values = cfg.k_values or (10,)
        max_k = max(k_values)
        queries = list(self._prepare_queries(cfg, queries_path))
        if cfg.max_queries:
            queries = queries[: cfg.max_queries]
        if not queries:
            LOGGER.warning("offline_eval.no_queries")
            return {"queries": 0, "summary": {}}

        per_query: list[dict[str, object]] = []
        aggregate = dict.fromkeys(k_values, 0.0)
        for query in queries:
            record, recall_per_k = self._evaluate_query(
                query=query,
                k_values=k_values,
                max_k=max_k,
            )
            per_query.append(record)
            for k, value in recall_per_k.items():
                aggregate[k] += value

        count = len(per_query)
        summary = {k: (aggregate[k] / count if count else 0.0) for k in k_values}
        output_root = self._resolve_output_dir(output_dir or cfg.output_dir)
        self._write_artifacts(output_root, per_query, summary)
        self._record_metrics(summary, count)
        LOGGER.info(
            "offline_eval.completed",
            extra={"queries": count, "output_dir": str(output_root), "summary": summary},
        )
        return {"queries": count, "summary": summary}

    def _resolve_output_dir(self, raw: str | Path) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self._repo_root / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _load_queries(source: Path | None) -> Iterable[EvalQuery] | None:
        if source is None:
            return None
        path = Path(source)
        if not path.exists():
            LOGGER.warning("offline_eval.queries_missing", extra={"path": str(path)})
            return None
        queries: list[EvalQuery] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                positives = tuple(int(pid) for pid in record.get("positives", []))
                queries.append(
                    EvalQuery(
                        qid=str(record.get("qid")),
                        text=str(record.get("text")),
                        positives=positives,
                        metadata=record.get("metadata"),
                    )
                )
        return queries

    def _synthesize_queries(self, cfg: EvalConfig) -> Iterable[EvalQuery]:
        self._symbol_catalog.ensure_schema()
        defs = self._symbol_catalog.fetch_symbol_defs(limit=cfg.max_queries)
        for row in defs:
            if row.chunk_id is None:
                continue
            query_text = self._build_question(row)
            yield EvalQuery(
                qid=row.symbol,
                text=query_text,
                positives=(row.chunk_id,),
                metadata={
                    "uri": row.uri,
                    "display_name": row.display_name,
                    "language": row.language,
                },
            )

    @staticmethod
    def _build_question(row: SymbolDefRow) -> str:
        base = f"Where is {row.display_name} defined?"
        language = (row.language or "").strip()
        if language:
            return f"{base} (language: {language})"
        return base

    def _embed_query(self, text: str) -> np.ndarray:
        vector = self._vllm.embed_single(text)
        return np.asarray(vector, dtype=np.float32).reshape(1, -1)

    @staticmethod
    def _write_artifacts(
        output_root: Path,
        per_query: Sequence[dict[str, object]],
        summary: dict[int, float],
    ) -> None:
        summary_path = output_root / "summary.json"
        detail_path = output_root / "per_query.jsonl"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {"summary": {str(k): v for k, v in summary.items()}, "queries": len(per_query)},
                handle,
                indent=2,
            )
        with detail_path.open("w", encoding="utf-8") as handle:
            for record in per_query:
                handle.write(json.dumps(record))
                handle.write("\n")

    @staticmethod
    def _record_metrics(summary: dict[int, float], query_count: int) -> None:
        OFFLINE_EVAL_QUERY_COUNT.set(float(query_count))
        for k, score in summary.items():
            OFFLINE_EVAL_RECALL_AT_K.labels(k=str(k)).set(float(score))

    def _prepare_queries(
        self,
        cfg: EvalConfig,
        queries_path: Path | None,
    ) -> Iterable[EvalQuery]:
        loaded = self._load_queries(queries_path)
        if loaded is not None:
            return loaded
        return self._synthesize_queries(cfg)

    def _evaluate_query(
        self,
        *,
        query: EvalQuery,
        k_values: Sequence[int],
        max_k: int,
    ) -> tuple[dict[str, object], dict[int, float]]:
        vector = self._embed_query(query.text)
        _, ids = self._faiss.search(vector, k=max_k)
        retrieved = [int(doc_id) for doc_id in ids[0].tolist()]
        positives = set(query.positives)
        recall_per_k: dict[int, float] = {}
        for k in k_values:
            if not positives:
                recall = 0.0
            else:
                recall = len(positives.intersection(retrieved[:k])) / float(len(positives))
            recall_per_k[k] = recall
        record: dict[str, object] = {
            "qid": query.qid,
            "text": query.text,
            "positives": list(query.positives),
            "recall": recall_per_k,
            "retrieved": retrieved,
        }
        return record, recall_per_k
