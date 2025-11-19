"""Shared reranker interfaces and request/response types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

__all__ = ["RerankRequest", "RerankResult", "Reranker", "ScoredDoc"]


@dataclass(slots=True, frozen=True)
class ScoredDoc:
    """Document identifier + score pair.

    Attributes
    ----------
    doc_id : int
        Document/chunk identifier.
    score : float
        Relevance score for this document. Higher scores indicate better matches.
    """

    doc_id: int
    score: float


@dataclass(slots=True, frozen=True)
class RerankResult:
    """Result emitted by rerankers.

    Attributes
    ----------
    doc_id : int
        Document/chunk identifier after reranking.
    score : float
        Reranked relevance score. Higher scores indicate better matches.
    """

    doc_id: int
    score: float


@dataclass(slots=True, frozen=True)
class RerankRequest:
    """Structured rerank invocation.

    Attributes
    ----------
    query : str
        Query string to rerank documents against.
    docs : Sequence[ScoredDoc]
        Sequence of scored documents to rerank.
    top_k : int
        Maximum number of results to return after reranking. Must be positive.
    explain : bool, optional
        Whether to include explanation metadata in results. Defaults to False.
    """

    query: str
    docs: Sequence[ScoredDoc]
    top_k: int
    explain: bool = False


class Reranker(Protocol):
    """Protocol implemented by pluggable rerankers."""

    name: str
    requires: frozenset[str]

    def rescore(self, request: RerankRequest) -> Sequence[RerankResult]:
        """Return rescored documents ordered by relevance."""
        ...
