"""Late-interaction rescoring wrappers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from codeintel_rev.io.xtr_manager import XTRIndex


@dataclass(slots=True, frozen=True)
class LateInteractionResult:
    """Rescoring payload returned by late-interaction engines."""

    ids: list[int]
    scores: list[float]
    explanations: list[tuple[int, dict[str, object]]] | None = None


class LateInteraction(Protocol):
    """Protocol implemented by late-interaction rescoring engines.

    Methods
    -------
    rescore(query, candidate_ids, *, explain, topk_explanations)
        Rescore candidate chunks using late-interaction methods.
    """


@dataclass(slots=True)
class XTRLateInteraction:
    """Late-interaction wrapper around :class:`codeintel_rev.io.xtr_manager.XTRIndex`."""

    index: XTRIndex

    def rescore(
        self,
        query: str,
        candidate_ids: Iterable[int],
        *,
        explain: bool = False,
        topk_explanations: int = 5,
    ) -> LateInteractionResult:
        """Rescore candidate chunks using XTR late-interaction.

        Parameters
        ----------
        query : str
            Query text for rescoring.
        candidate_ids : Iterable[int]
            Chunk IDs to rescore.
        explain : bool, optional
            Whether to include explanation metadata (default: False).
        topk_explanations : int, optional
            Number of top explanations to include (default: 5).

        Returns
        -------
        LateInteractionResult
            Rescored results with IDs, scores, and optional explanations.
        """
        triples = self.index.rescore(
            query=query,
            candidate_chunk_ids=list(candidate_ids),
            explain=explain,
            topk_explanations=topk_explanations,
        )
        ids = [int(row[0]) for row in triples]
        scores = [float(row[1]) for row in triples]
        explanations = (
            [(int(row[0]), dict(row[2])) for row in triples if len(row) > 2 and row[2] is not None]
            if explain
            else None
        )
        return LateInteractionResult(ids=ids, scores=scores, explanations=explanations)


__all__ = ["LateInteraction", "LateInteractionResult", "XTRLateInteraction"]
