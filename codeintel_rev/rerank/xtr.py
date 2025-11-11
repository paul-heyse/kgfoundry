"""XTR-backed reranker implementation."""

from __future__ import annotations

from collections.abc import Sequence

from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.rerank.base import Reranker, RerankRequest, RerankResult

__all__ = ["XTRReranker"]


class XTRReranker(Reranker):
    """Rerank hits using the XTR MaxSim scorer."""

    name = "xtr"
    requires = frozenset({"xtr_index_present", "torch_importable"})

    def __init__(self, index: XTRIndex) -> None:
        self._index = index

    def rescore(self, request: RerankRequest) -> Sequence[RerankResult]:
        """Return docs rescored by XTR MaxSim.

        Returns
        -------
        Sequence[RerankResult]
            Documents ordered by reranker scores.
        """
        if not request.docs or self._index is None or not self._index.ready:
            return [RerankResult(doc.doc_id, doc.score) for doc in request.docs]
        candidate_ids = [doc.doc_id for doc in request.docs[: max(1, request.top_k)]]
        hits = self._index.rescore(
            query=request.query,
            candidate_chunk_ids=candidate_ids,
            explain=request.explain,
        )
        score_map = {int(chunk_id): float(score) for chunk_id, score, _payload in hits}
        return sorted(
            (
                RerankResult(
                    doc_id=scored.doc_id,
                    score=score_map.get(scored.doc_id, scored.score),
                )
                for scored in request.docs
            ),
            key=lambda item: item.score,
            reverse=True,
        )
