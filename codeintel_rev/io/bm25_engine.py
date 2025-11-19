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
    """Narrow engine that delegates to a backend and normalizes outputs.

    Attributes
    ----------
    backend : BM25Backend
        BM25 backend implementation providing search capabilities.
    """

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
    """RM3 parameters used by :class:`PyseriniBM25Backend`.

    Attributes
    ----------
    params : RM3Params | None, optional
        RM3 pseudo-relevance feedback parameters. None disables RM3.
        Defaults to None.
    heuristics : RM3Heuristics | None, optional
        Heuristics for deciding when to enable RM3 automatically. None disables
        automatic RM3. Defaults to None.
    enable_rm3 : bool, optional
        Whether RM3 is explicitly enabled. Defaults to False.
    auto_rm3 : bool, optional
        Whether to automatically enable RM3 based on heuristics. Defaults to False.
    """

    params: RM3Params | None = None
    heuristics: RM3Heuristics | None = None
    enable_rm3: bool = False
    auto_rm3: bool = False


class PyseriniBM25Backend(BM25Backend):
    """Pyserini-backed BM25 implementation with optional RM3 heuristics.

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

    def __init__(
        self,
        index_dir: Path,
        *,
        k1: float,
        b: float,
        rm3: BM25Rm3Config | None = None,
    ) -> None:
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
        """Create a new Lucene searcher instance configured with BM25 parameters.

        Returns
        -------
        _LuceneSearcher
            A Lucene searcher instance bound to the index directory and configured
            with the k1 and b BM25 parameters from this backend's configuration.
        """
        lucene = _lucene.module()
        searcher = cast("_LuceneSearcher", lucene.LuceneSearcher(str(self._index_dir)))
        try:
            searcher.set_bm25(self._k1, self._b)
        except TypeError:  # pragma: no cover - depends on Pyserini version
            searcher.set_bm25(k1=self._k1, b=self._b)
        return searcher

    def _ensure_rm3_searcher(self) -> _LuceneSearcher:
        """Create or return a cached RM3-configured searcher instance.

        Returns
        -------
        _LuceneSearcher
            A Lucene searcher instance configured with RM3 query expansion
            parameters. The searcher is cached after first creation to avoid
            redundant initialization overhead.
        """
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
        """Determine whether RM3 query expansion should be used for a query.

        Parameters
        ----------
        query_text : str
            The query text to evaluate for RM3 eligibility.

        Returns
        -------
        bool
            True if RM3 should be enabled for this query based on configuration
            and heuristics. False if RM3 should be disabled or auto-detection
            determines it's not beneficial.
        """
        if self._rm3_enabled_default and not self._auto_rm3:
            return True
        if not self._auto_rm3:
            return False
        if self._heuristics is None:
            return self._rm3_enabled_default
        return self._heuristics.should_enable(query_text)


def _safe_int(value: object) -> int | None:
    """Convert a value to an integer, returning None on failure.

    Parameters
    ----------
    value : object
        Value to convert to an integer. Can be any type that can be converted
        via str() and then int().

    Returns
    -------
    int | None
        The integer representation of the value, or None if conversion fails
        due to TypeError or ValueError.
    """
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
    """Protocol describing a Lucene search result hit.

    Attributes
    ----------
    docid : str | int
        Document identifier from the search result.
    score : float
        Relevance score assigned by the search engine.
    """

    docid: str | int
    score: float


class _LuceneSearcher(Protocol):
    """Protocol describing the Pyserini Lucene searcher interface.

    This protocol abstracts the Pyserini LuceneSearcher API to enable
    type-safe interaction with search functionality while maintaining
    compatibility across different Pyserini versions.
    """

    def search(self, query_text: str, k: int) -> TypingSequence[_LuceneHit]:
        """Search the index for documents matching the query.

        Parameters
        ----------
        query_text : str
            Query string to search for.
        k : int
            Maximum number of results to return.

        Returns
        -------
        TypingSequence[_LuceneHit]
            Sequence of search hits ordered by relevance score descending.
        """
        ...

    def set_bm25(self, k1: float, b: float) -> None:
        """Configure BM25 ranking parameters.

        Parameters
        ----------
        k1 : float
            Term frequency saturation parameter.
        b : float
            Length normalization parameter.
        """
        ...

    def set_rm3(self, fb_docs: int, fb_terms: int, original_query_weight: float) -> None:
        """Configure RM3 query expansion parameters.

        Parameters
        ----------
        fb_docs : int
            Number of feedback documents to use for expansion.
        fb_terms : int
            Number of expansion terms to add to the query.
        original_query_weight : float
            Weight given to the original query terms versus expansion terms.
        """
        ...

    def set_analyzer(self, analyzer: str) -> None:
        """Set the text analyzer for query processing.

        Parameters
        ----------
        analyzer : str
            Name of the analyzer to use (e.g., "english", "standard").
        """
        ...
