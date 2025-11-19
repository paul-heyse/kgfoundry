"""Late-interaction rescoring wrappers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, cast

from codeintel_rev.io.xtr_manager import XTRIndex

_DEFAULT_TOPK_EXPLANATIONS: Final[int] = 5
_EXPLANATION_INDEX: Final[int] = 2


@dataclass(frozen=True, slots=True)
class LateInteractionResult:
    """Rescoring payload returned by late-interaction engines."""

    ids: list[int]
    scores: list[float]
    explanations: list[tuple[int, dict[str, object]]] | None = None


class LateInteraction(Protocol):
    """Protocol implemented by late-interaction rescoring engines."""

    def rescore(
        self,
        query: str,
        candidate_ids: Iterable[int],
        *,
        explain: bool = False,
    ) -> LateInteractionResult:
        """Rescore candidate documents."""
        ...


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
        topk_explanations: int = _DEFAULT_TOPK_EXPLANATIONS,
    ) -> LateInteractionResult:
        """Rescore candidate IDs using the XTR narrow-mode API.

        Parameters
        ----------
        query : str
            Query text to use for rescoring.
        candidate_ids : Iterable[int]
            Iterable of document/chunk IDs to rescore.
        explain : bool, optional
            Whether to include explanation metadata in the result. Defaults to False.
        topk_explanations : int, optional
            Maximum number of explanations to include per result when explain=True.
            Defaults to 5.

        Returns
        -------
        LateInteractionResult
            Rescored identifiers, scores, and optional explanations.
        """
        triples: Sequence[tuple[int, float, Mapping[str, object] | None]]
        triples = self.index.rescore(
            query=query,
            candidate_chunk_ids=list(candidate_ids),
            explain=explain,
            topk_explanations=topk_explanations,
        )
        ids = [int(row[0]) for row in triples]
        scores = [float(row[1]) for row in triples]
        explanations = (
            [
                (
                    int(row[0]),
                    dict(cast("Mapping[str, object]", row[_EXPLANATION_INDEX])),
                )
                for row in triples
                if len(row) > _EXPLANATION_INDEX and row[_EXPLANATION_INDEX] is not None
            ]
            if explain
            else None
        )
        return LateInteractionResult(ids=ids, scores=scores, explanations=explanations)


__all__ = ["LateInteraction", "LateInteractionResult", "XTRLateInteraction"]
