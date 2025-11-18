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

if TYPE_CHECKING:
    from codeintel_rev.config.paths import ResolvedPaths


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
        """Initialize offline recall evaluator.

        Parameters
        ----------
        settings : Settings
            Application settings.
        paths : PathsConfig | ResolvedPaths
            Resolved application paths.
        faiss_manager : FAISSManager
            FAISS manager for vector search.
        vllm_client : VLLMClient
            VLLM client for query embedding.
        duckdb_manager : DuckDBManager
            DuckDB manager for catalog access.
        """
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
        return {"queries": count, "summary": summary}

    def _resolve_output_dir(self, raw: str | Path) -> Path:
        """Resolve and create output directory for evaluation artifacts.

        This method converts a path specification (absolute or relative) into a
        normalized absolute Path and ensures the directory exists. Relative paths
        are resolved relative to the repository root, enabling portable configuration.
        The directory is created if it doesn't exist, including any necessary parent
        directories.

        Parameters
        ----------
        raw : str | Path
            Output directory path specification. May be absolute or relative to the
            repository root. The path is normalized and created if missing.

        Returns
        -------
        Path
            Absolute, normalized path to the output directory. The directory is
            guaranteed to exist (created if necessary) and is ready for writing
            evaluation artifacts.

        Notes
        -----
        This method ensures that evaluation output directories are properly resolved
        and created, handling both absolute and relative path specifications. The
        method creates parent directories as needed, ensuring that nested directory
        structures can be specified without manual creation.
        """
        path = Path(raw)
        if not path.is_absolute():
            path = self._repo_root / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _load_queries(source: Path | None) -> Iterable[EvalQuery] | None:
        """Load evaluation queries from a JSONL file.

        This static method reads evaluation queries from a JSONL (JSON Lines) file,
        where each line contains a JSON object with query ID, text, and positive
        example chunk IDs. The method handles file reading errors gracefully and
        skips empty lines. Used to load curated evaluation queries for offline
        recall evaluation.

        Parameters
        ----------
        source : Path | None
            Path to JSONL file containing evaluation queries. Each line should be
            a JSON object with "qid", "text", "positives" (list of chunk IDs), and
            optional "metadata" fields. If None, returns None to indicate queries
            should be synthesized.

        Returns
        -------
        Iterable[EvalQuery] | None
            Iterable of EvalQuery objects if the file exists and is readable, or
            None if source is None or the file doesn't exist. Empty files return
            an empty iterable.

        Notes
        -----
        This method provides a way to load pre-curated evaluation queries from
        external files, enabling reproducible evaluation with known ground truth.
        The JSONL format allows streaming of large query sets without loading
        everything into memory at once.
        """
        if source is None:
            return None
        path = Path(source)
        if not path.exists():
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
        """Synthesize evaluation queries from symbol definitions in the catalog.

        This method generates evaluation queries by extracting symbol definitions
        from the DuckDB symbol catalog and converting them into natural language
        questions. Each symbol definition becomes a query asking "Where is {symbol}
        defined?", with the symbol's chunk ID as the positive example. This enables
        evaluation without manually curated queries by leveraging existing symbol
        metadata.

        Parameters
        ----------
        cfg : EvalConfig
            Evaluation configuration containing limits and synthesis parameters.
            The max_queries setting limits the number of synthesized queries.

        Yields
        ------
        EvalQuery
            Evaluation query objects with synthesized question text, symbol ID as
            query ID, and the symbol's chunk ID as the positive example. Queries
            include metadata about the symbol (URI, display name, language).

        Notes
        -----
        Query synthesis enables automatic evaluation setup by generating queries
        from existing symbol definitions. This is particularly useful for initial
        evaluation or when curated queries are unavailable. The synthesized queries
        test whether the retrieval system can find symbol definitions, which is a
        common use case for code search systems.
        """
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
        """Build a natural language question from a symbol definition row.

        This static method converts a symbol definition into a natural language
        question suitable for evaluation queries. The question asks where the
        symbol is defined, optionally including language information if available.
        The generated questions simulate real user queries for symbol location.

        Parameters
        ----------
        row : SymbolDefRow
            Symbol definition row containing display name and optional language
            information. The row represents a symbol that should be findable via
            retrieval.

        Returns
        -------
        str
            Natural language question string asking where the symbol is defined.
            Format: "Where is {display_name} defined?" or "Where is {display_name}
            defined? (language: {language})" if language is available.

        Notes
        -----
        This method generates evaluation queries that test whether the retrieval
        system can answer common developer questions about symbol locations. The
        questions are designed to be realistic and test the system's ability to
        match natural language queries to code locations.
        """
        base = f"Where is {row.display_name} defined?"
        language = (row.language or "").strip()
        if language:
            return f"{base} (language: {language})"
        return base

    def _embed_query(self, text: str) -> np.ndarray:
        """Embed a query text into a vector representation for FAISS search.

        This method converts a natural language query string into a dense vector
        embedding using the configured VLLM embedding service. The embedding is
        formatted as a 2D numpy array (1 x embedding_dim) suitable for FAISS
        similarity search. The embedding enables semantic search by converting
        text queries into the same vector space as indexed code chunks.

        Parameters
        ----------
        text : str
            Natural language query text to embed. The text is passed to the
            embedding service to generate a vector representation.

        Returns
        -------
        np.ndarray
            2D numpy array of shape (1, embedding_dim) containing the query
            embedding vector. The array is float32 dtype for FAISS compatibility
            and is reshaped to ensure correct dimensions for search operations.

        Notes
        -----
        Query embedding is the first step in semantic search, converting text
        queries into vectors that can be compared against indexed code chunks.
        The embedding preserves semantic meaning, enabling the system to find
        relevant code even when query text doesn't exactly match code content.
        """
        vector = self._vllm.embed_single(text)
        return np.asarray(vector, dtype=np.float32).reshape(1, -1)

    @staticmethod
    def _write_artifacts(
        output_root: Path,
        per_query: Sequence[dict[str, object]],
        summary: dict[int, float],
    ) -> None:
        """Write evaluation artifacts to the output directory.

        This static method persists evaluation results to disk, writing both aggregate
        summary statistics and per-query detailed results. The summary file contains
        aggregate recall metrics across all queries, while the per-query file contains
        detailed results for each individual query. Both files use JSON formats for
        easy analysis and integration with reporting tools.

        Parameters
        ----------
        output_root : Path
            Output directory where evaluation artifacts should be written. The
            directory must exist and be writable.
        per_query : Sequence[dict[str, object]]
            Sequence of per-query evaluation records, each containing query ID, text,
            retrieved chunk IDs, recall metrics, and other metadata. Written to
            per_query.jsonl in JSONL format.
        summary : dict[int, float]
            Aggregate recall statistics keyed by k value. Contains average recall
            at each k value across all queries. Written to summary.json.

        Notes
        -----
        This method writes evaluation artifacts in standard formats (JSON and JSONL)
        that are easy to parse and analyze. The summary file provides quick overview
        metrics, while the per-query file enables detailed analysis of individual
        query performance. Both files are essential for understanding retrieval system
        performance and identifying areas for improvement.
        """
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

    def _prepare_queries(
        self,
        cfg: EvalConfig,
        queries_path: Path | None,
    ) -> Iterable[EvalQuery]:
        """Prepare evaluation queries from file or synthesis.

        This method prepares evaluation queries by first attempting to load them
        from a file if provided, and falling back to synthesis from the symbol
        catalog if no file is specified or the file doesn't exist. This enables
        flexible evaluation setup supporting both curated queries and automatic
        query generation.

        Parameters
        ----------
        cfg : EvalConfig
            Evaluation configuration containing synthesis parameters and limits.
            Used when synthesizing queries from the symbol catalog.
        queries_path : Path | None
            Optional path to JSONL file containing curated evaluation queries.
            If provided and the file exists, queries are loaded from the file.
            If None or the file doesn't exist, queries are synthesized.

        Returns
        -------
        Iterable[EvalQuery]
            Iterable of evaluation queries, either loaded from file or synthesized
            from the symbol catalog. The queries are ready for evaluation execution.

        Notes
        -----
        This method provides a unified interface for query preparation, handling
        both curated and synthesized queries transparently. Curated queries enable
        precise evaluation with known ground truth, while synthesis enables quick
        evaluation setup without manual query curation. The method prioritizes
        file-based queries when available, falling back to synthesis only when
        necessary.
        """
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
        """Evaluate a single query against the FAISS index and compute recall metrics.

        This method performs the core evaluation logic for a single query: embedding
        the query text, searching the FAISS index, and computing recall metrics at
        multiple k values. Recall is computed as the fraction of positive examples
        found in the top-k retrieved results. The method returns both detailed
        per-query results and recall metrics for aggregation.

        Parameters
        ----------
        query : EvalQuery
            Evaluation query containing query ID, text, and positive example chunk
            IDs. The query text is embedded and searched against the FAISS index.
        k_values : Sequence[int]
            Sequence of k values at which to compute recall metrics. Each k value
            represents the number of top results to consider when computing recall.
        max_k : int
            Maximum k value for FAISS search. The search retrieves max_k results,
            and recall is computed for each requested k value from this result set.

        Returns
        -------
        tuple[dict[str, object], dict[int, float]]
            Tuple containing:
            - Per-query evaluation record with query ID, text, retrieved chunk IDs,
              recall metrics, and positive examples.
            - Dictionary mapping k values to recall scores for this query.

        Notes
        -----
        This method performs the core recall evaluation by comparing retrieved
        results against known positive examples. Recall measures the fraction of
        relevant items found, making it ideal for evaluating retrieval system
        performance. The method computes recall at multiple k values to understand
        how performance varies with result set size, enabling analysis of precision-
        recall tradeoffs.
        """
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
