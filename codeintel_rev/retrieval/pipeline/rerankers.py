"""LLM reranker adapters."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol


@dataclass(slots=True, frozen=True)
class Doc:
    """Minimal document payload passed to rerankers."""

    id: int
    uri: str | None = None
    snippet: str | None = None


@dataclass(slots=True, frozen=True)
class RerankResult:
    """Normalized rerank result."""

    ids: list[int]
    scores: list[float]


class Reranker(Protocol):
    """Protocol implemented by reranking providers.

    Methods
    -------
    rerank(query, docs)
        Rerank documents based on query relevance.
    """


class NoopReranker:
    """No-op reranker that preserves ordering."""

    def rerank(self, _query: str, docs: Sequence[Doc]) -> RerankResult:  # noqa: PLR6301
        """Preserve document ordering without reranking.

        Parameters
        ----------
        _query : str
            Query text (unused in no-op implementation).
        docs : Sequence[Doc]
            Documents to process.

        Returns
        -------
        RerankResult
            Result with original document order and zero scores.
        """
        ids = [doc.id for doc in docs]
        return RerankResult(ids=ids, scores=[0.0 for _ in ids])


if TYPE_CHECKING:
    from codeintel_rev.io.rerank_coderankllm import (
        CodeRankListwiseReranker as _CodeRankListwiseReranker,
    )
else:  # pragma: no cover - typing only
    _CodeRankListwiseReranker = Any

try:
    from codeintel_rev.io.rerank_coderankllm import (
        CodeRankListwiseReranker as _RuntimeCodeRankListwiseReranker,
    )
except (AttributeError, ImportError):  # pragma: no cover - optional dependency
    _RuntimeCodeRankListwiseReranker = None

if _RuntimeCodeRankListwiseReranker is not None:

    @dataclass(slots=True)
    class _CodeRankLLMAdapter:
        """Adapter around :class:`CodeRankListwiseReranker`."""

        reranker: _CodeRankListwiseReranker

        def rerank(self, query: str, docs: Sequence[Doc]) -> RerankResult:
            """Rerank documents using CodeRank LLM reranker.

            Parameters
            ----------
            query : str
                Query text for reranking.
            docs : Sequence[Doc]
                Documents to rerank.

            Returns
            -------
            RerankResult
                Reranked results with IDs and scores ordered by relevance.
            """
            pairs = []
            for doc in docs:
                snippet = (doc.snippet or "").strip()
                if not snippet:
                    snippet = (doc.uri or "").strip()
                pairs.append((doc.id, snippet))
            if not pairs:
                return RerankResult(ids=[], scores=[])

            ordered_ids = self.reranker.rerank(query, pairs)
            weights = {
                chunk_id: float(len(ordered_ids) - rank)
                for rank, chunk_id in enumerate(ordered_ids)
            }
            scored = [(cid, weights.get(cid, 0.0)) for cid, _ in pairs]
            scored.sort(key=lambda item: item[1], reverse=True)
            return RerankResult(
                ids=[cid for cid, _ in scored],
                scores=[score for _, score in scored],
            )

    CodeRankLLMAdapter: type[_CodeRankLLMAdapter] | None = _CodeRankLLMAdapter
else:  # pragma: no cover - dependency gated
    CodeRankLLMAdapter = None


__all__ = ["CodeRankLLMAdapter", "Doc", "NoopReranker", "RerankResult", "Reranker"]
