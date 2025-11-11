"""Shared reranker interfaces and request/response types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

__all__ = ["RerankRequest", "RerankResult", "Reranker", "ScoredDoc"]


@dataclass(slots=True, frozen=True)
class ScoredDoc:
    """Document identifier + score pair."""

    doc_id: int
    score: float


@dataclass(slots=True, frozen=True)
class RerankResult:
    """Result emitted by rerankers."""

    doc_id: int
    score: float


@dataclass(slots=True, frozen=True)
class RerankRequest:
    """Structured rerank invocation."""

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
