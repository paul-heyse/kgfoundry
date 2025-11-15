"""SCIP symbol coverage evaluator."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

import numpy as np

from codeintel_rev.config.settings import Settings
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import SearchRuntimeOverrides
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


class SupportsFaissSearch(Protocol):
    """Protocol capturing the subset of FAISS search methods required here."""

    def search(
        self,
        query: np.ndarray,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: SearchRuntimeOverrides | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return distances and ids for ``query``."""
        ...


class SupportsEmbedSingle(Protocol):
    """Protocol describing embedder behaviour used by the evaluator."""

    def embed_single(self, text: str) -> Sequence[float] | np.ndarray:
        """Return an embedding vector for ``text``."""
        ...


@dataclass(slots=True, frozen=True)
class CoverageResult:
    """Container for per-symbol coverage evaluation."""

    symbol: str
    chunk_id: int | None
    chunk_covered: bool
    index_covered: bool
    retrieved: bool


class CoverageSummary(TypedDict):
    """Typed summary payload returned by ``SCIPCoverageEvaluator``."""

    total: int
    chunk_coverage: float
    index_coverage: float
    retrieval_coverage: float
    k: int


class SCIPCoverageEvaluator:
    """Evaluate chunk/index/retrieval coverage across SCIP function definitions."""

    def __init__(
        self,
        *,
        settings: Settings,
        repo_root: str | Path,
        duckdb_manager: DuckDBManager,
        faiss_manager: SupportsFaissSearch,
        vllm_client: SupportsEmbedSingle,
    ) -> None:
        self._settings = settings
        self._repo_root = Path(repo_root)
        self._duckdb = duckdb_manager
        self._faiss = faiss_manager
        self._vllm = vllm_client
        self._symbol_catalog = SymbolCatalog(duckdb_manager)

    def run(
        self,
        *,
        k: int = 10,
        limit: int | None = None,
        output_dir: Path | None = None,
    ) -> CoverageSummary:
        """Execute the coverage evaluation and return summary metrics.

        Extended Summary
        ----------------
        This method runs SCIP function coverage evaluation by fetching symbol
        definitions from the DuckDB catalog, performing FAISS searches for each
        symbol's embedding, and computing coverage metrics (how many symbols are
        retrievable at top-k). Results are written to the output directory as JSON
        reports. Used for validating that symbol definitions are searchable in
        the FAISS index.

        Parameters
        ----------
        k : int, optional
            Top-k value for retrieval evaluation (default: 10). Coverage is computed
            as the fraction of symbols that appear in the top-k FAISS results for
            their own embeddings.
        limit : int | None, optional
            Optional limit on the number of symbols to evaluate. If None, evaluates
            all symbols in the catalog. Useful for quick validation runs.
        output_dir : Path | None, optional
            Directory for coverage artifacts (JSON reports). If None, uses
            `settings.eval.output_dir`.

        Returns
        -------
        CoverageSummary
            Summary dataclass with coverage metrics including total symbol count,
            coverage percentage, and per-symbol retrieval results.

        Notes
        -----
        This method performs coverage evaluation by iterating over symbol definitions
        and checking if they appear in FAISS search results. Coverage artifacts are
        written to the output directory for analysis. Time complexity: O(n_symbols * search_time)
        where search_time depends on index size and k.
        """
        defs = self._symbol_catalog.fetch_symbol_defs(limit=limit)
        if not defs:
            LOGGER.warning("scip_coverage.no_symbols")
            empty_summary: CoverageSummary = {
                "total": 0,
                "chunk_coverage": 0.0,
                "index_coverage": 0.0,
                "retrieval_coverage": 0.0,
                "k": k,
            }
            return empty_summary

        chunk_ids = [row.chunk_id for row in defs if row.chunk_id is not None]
        chunk_presence = self._lookup_chunk_ids(chunk_ids)

        per_symbol: list[CoverageResult] = []
        retrieval_hits = 0
        chunk_hits = 0
        index_hits = 0

        for row in defs:
            result = self._evaluate_symbol(row, chunk_presence, k)
            per_symbol.append(result)
            chunk_hits += int(result.chunk_covered)
            index_hits += int(result.index_covered)
            retrieval_hits += int(result.retrieved)

        total = len(defs)
        summary: CoverageSummary = {
            "total": total,
            "chunk_coverage": chunk_hits / total if total else 0.0,
            "index_coverage": index_hits / total if total else 0.0,
            "retrieval_coverage": retrieval_hits / total if total else 0.0,
            "k": k,
        }
        resolved_output = output_dir or self._settings.eval.output_dir
        self._write_artifacts(per_symbol, summary, resolved_output)
        LOGGER.info(
            "scip_coverage.completed",
            extra={"summary": summary, "output_dir": output_dir or self._settings.eval.output_dir},
        )
        return summary

    def _lookup_chunk_ids(self, chunk_ids: Sequence[int]) -> set[int]:
        if not chunk_ids:
            return set()
        with self._duckdb.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.id
                FROM chunks AS c
                INNER JOIN UNNEST(?) AS t(chunk_id)
                  ON c.id = t.chunk_id
                """,
                [list(chunk_ids)],
            ).fetchall()
        return {int(row[0]) for row in rows}

    def _embed(self, text: str) -> np.ndarray:
        embedding = self._vllm.embed_single(text)
        return np.asarray(embedding, dtype=np.float32).reshape(1, -1)

    @staticmethod
    def _question_for(row: SymbolDefRow) -> str:
        language = (row.language or "").strip()
        base = f"Find the definition of {row.display_name}"
        if language:
            return f"{base} in {language}"
        return base

    def _write_artifacts(
        self,
        per_symbol: Sequence[CoverageResult],
        summary: CoverageSummary,
        output_dir: Path | str,
    ) -> None:
        base = Path(output_dir)
        if not base.is_absolute():
            base = self._repo_root / base
        base.mkdir(parents=True, exist_ok=True)
        (base / "coverage_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        detail_path = base / "coverage_details.jsonl"
        with detail_path.open("w", encoding="utf-8") as handle:
            for result in per_symbol:
                handle.write(
                    json.dumps(
                        {
                            "symbol": result.symbol,
                            "chunk_id": result.chunk_id,
                            "chunk_covered": result.chunk_covered,
                            "index_covered": result.index_covered,
                            "retrieved": result.retrieved,
                        }
                    )
                )
                handle.write("\n")

    def _evaluate_symbol(
        self,
        row: SymbolDefRow,
        chunk_presence: set[int],
        k: int,
    ) -> CoverageResult:
        chunk_id = row.chunk_id
        chunk_covered = chunk_id is not None
        index_covered = chunk_id in chunk_presence if chunk_covered else False
        retrieved = False
        if chunk_id is not None and index_covered:
            question = self._question_for(row)
            vector = self._embed(question)
            _, ids = self._faiss.search(vector, k=k)
            retrieved_ids = {int(doc_id) for doc_id in ids[0].tolist()}
            retrieved = chunk_id in retrieved_ids
        return CoverageResult(
            symbol=row.symbol,
            chunk_id=chunk_id,
            chunk_covered=chunk_covered,
            index_covered=index_covered,
            retrieved=retrieved,
        )
