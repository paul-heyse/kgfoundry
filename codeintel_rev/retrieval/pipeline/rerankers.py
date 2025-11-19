"""LLM reranker adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankResult:
    """Normalized rerank result.

    Attributes
    ----------
    ids : list[int]
        List of document/chunk IDs after reranking, sorted by score descending.
    scores : list[float]
        List of reranked relevance scores corresponding to ids. Higher scores
        indicate better matches.
    """

    ids: list[int]
    scores: list[float]


class Reranker(Protocol):
    """Protocol implemented by reranking providers."""

    def rerank(self, query: str, ids: Iterable[int], scores: Iterable[float]) -> RerankResult:
        """Return reranked IDs and scores for the provided documents."""
        ...


class NoopReranker:
    """No-op reranker that preserves ordering."""

    @staticmethod
    def rerank(_query: str, ids: Iterable[int], scores: Iterable[float]) -> RerankResult:
        """Return the provided identifiers and scores unchanged.

        Parameters
        ----------
        _query : str
            Query text (unused by no-op reranker).
        ids : Iterable[int]
            Document/chunk IDs to rerank.
        scores : Iterable[float]
            Initial relevance scores.

        Returns
        -------
        RerankResult
            Result with original ordering preserved, containing the same IDs
            and scores in the same order as the input.
        """
        ids_list = [int(i) for i in ids]
        scores_list = [float(s) for s in scores]
        return RerankResult(ids=ids_list, scores=scores_list)


__all__ = ["NoopReranker", "RerankResult", "Reranker"]
