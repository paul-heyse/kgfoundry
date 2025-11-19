"""Narrow BM25 engine and backend protocols."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Sequence as TypingSequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params

_lucene = LazyModule("pyserini.search.lucene", "bm25 search runtime")


class BM25Backend(Protocol):
    """Minimal surface for BM25 search backends."""

    def search(self, query_text: str, k: int) -> Sequence[tuple[int, float]]:
        """Return ``(doc_id, score)`` pairs for ``query_text``."""
        ...


@dataclass(frozen=True, slots=True)
class BM25Engine:
    """Narrow engine that delegates to a backend and normalizes outputs."""

    backend: BM25Backend

    def search(self, query_text: str, *, k: int) -> list[tuple[int, float]]:
        """Search BM25 index for query text.

        Parameters
        ----------
        query_text : str
            Query string to search for.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) pairs, sorted by score descending.
        """
        if k <= 0:
            return []
        hits = self.backend.search(query_text, k)
        return [(int(doc_id), float(score)) for doc_id, score in hits][:k]

    def serialize_method(self) -> dict[str, object]:
        """Serialize engine configuration for logging/debugging.

        Returns
        -------
        dict[str, object]
            Dictionary with channel name and backend implementation class name.
        """
        return {"channel": "bm25", "impl": type(self.backend).__name__}


@dataclass(frozen=True, slots=True)
class BM25Rm3Config:
    """RM3 parameters used by :class:`PyseriniBM25Backend`."""

    params: RM3Params | None = None
    heuristics: RM3Heuristics | None = None
    enable_rm3: bool = False
    auto_rm3: bool = False


class PyseriniBM25Backend(BM25Backend):
    """Pyserini-backed BM25 implementation with optional RM3 heuristics."""

    def __init__(
        self,
        index_dir: Path,
        *,
        k1: float,
        b: float,
        rm3: BM25Rm3Config | None = None,
    ) -> None:
        """Initialize Pyserini BM25 backend.

        Parameters
        ----------
        index_dir : Path
            Path to the Lucene BM25 index directory.
        k1 : float
            BM25 k1 parameter (term frequency saturation).
        b : float
            BM25 b parameter (length normalization).
        rm3 : BM25Rm3Config | None, optional
            Optional RM3 query expansion configuration.

        Raises
        ------
        FileNotFoundError
            If the index directory does not exist.
        """
        if not index_dir.exists():
            msg = f"BM25 index not found: {index_dir}"
            raise FileNotFoundError(msg)
        rm3_cfg = rm3 or BM25Rm3Config()
        self._index_dir = index_dir
        self._k1 = float(k1)
        self._b = float(b)
        self._rm3_params = rm3_cfg.params or RM3Params()
        self._heuristics = rm3_cfg.heuristics if rm3_cfg.auto_rm3 else None
        self._rm3_enabled_default = rm3_cfg.enable_rm3
        self._auto_rm3 = rm3_cfg.auto_rm3
        self._base_searcher = self._create_searcher()
        self._rm3_searcher: _LuceneSearcher | None = None

    def search(self, query_text: str, k: int) -> list[tuple[int, float]]:
        """Search BM25 index with optional RM3 query expansion.

        Parameters
        ----------
        query_text : str
            Query string to search for.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) pairs, sorted by score descending.

        Raises
        ------
        RuntimeError
            If the underlying Pyserini searcher fails.
        """
        if k <= 0:
            return []
        use_rm3 = self._should_use_rm3(query_text)
        searcher = self._ensure_rm3_searcher() if use_rm3 else self._base_searcher
        try:
            hits = searcher.search(query_text, k=k)
        except Exception as exc:  # pragma: no cover - Pyserini raises
            msg = "BM25 search failed"
            raise RuntimeError(msg) from exc
        results: list[tuple[int, float]] = []
        for hit in hits:
            doc_id = _safe_int(hit.docid)
            if doc_id is None:
                continue
            results.append((doc_id, float(hit.score)))
        return results

    def _create_searcher(self) -> _LuceneSearcher:
        lucene = _lucene.module()
        searcher = cast("_LuceneSearcher", lucene.LuceneSearcher(str(self._index_dir)))
        try:
            searcher.set_bm25(self._k1, self._b)
        except TypeError:  # pragma: no cover - depends on Pyserini version
            searcher.set_bm25(k1=self._k1, b=self._b)
        return searcher

    def _ensure_rm3_searcher(self) -> _LuceneSearcher:
        if self._rm3_searcher is not None:
            return self._rm3_searcher
        searcher = self._create_searcher()
        params = self._rm3_params
        try:
            searcher.set_rm3(params.fb_docs, params.fb_terms, params.orig_weight)
        except TypeError:  # pragma: no cover - depends on Pyserini version
            searcher.set_rm3(
                fb_docs=params.fb_docs,
                fb_terms=params.fb_terms,
                original_query_weight=params.orig_weight,
            )
        self._rm3_searcher = searcher
        return searcher

    def _should_use_rm3(self, query_text: str) -> bool:
        if self._rm3_enabled_default and not self._auto_rm3:
            return True
        if not self._auto_rm3:
            return False
        if self._heuristics is None:
            return self._rm3_enabled_default
        return self._heuristics.should_enable(query_text)


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


__all__ = [
    "BM25Backend",
    "BM25Engine",
    "BM25Rm3Config",
    "PyseriniBM25Backend",
]


class _LuceneHit(Protocol):
    docid: str | int
    score: float


class _LuceneSearcher(Protocol):
    def search(self, query_text: str, k: int) -> TypingSequence[_LuceneHit]: ...

    def set_bm25(self, k1: float, b: float) -> None: ...

    def set_rm3(self, fb_docs: int, fb_terms: int, original_query_weight: float) -> None: ...

    def set_analyzer(self, analyzer: str) -> None: ...
