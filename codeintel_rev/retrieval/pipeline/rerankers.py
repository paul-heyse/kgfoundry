"""LLM reranker adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankResult:
    """Normalized rerank result."""

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

        Returns
        -------
        RerankResult
            Result with original ordering preserved.
        """
        ids_list = [int(i) for i in ids]
        scores_list = [float(s) for s in scores]
        return RerankResult(ids=ids_list, scores=scores_list)


__all__ = ["NoopReranker", "RerankResult", "Reranker"]
