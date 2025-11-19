"""Pure fusion protocol abstractions for hybrid retrieval."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from codeintel_rev.retrieval.fusion.weighted_rrf import fuse_weighted_rrf
from codeintel_rev.retrieval.types import SearchHit


@dataclass(frozen=True, slots=True)
class FusionInput:
    """Per-channel candidates that will be fused via Reciprocal Rank Fusion."""

    channel: str
    candidates: Sequence[tuple[int, float]]


@dataclass(frozen=True, slots=True)
class FusionOptions:
    """Fusion configuration knobs."""

    weights: Mapping[str, float] | None = None
    k: int = 50
    base: int = 60


class FusionProtocol(Protocol):
    """Contract for pure fusion strategies."""

    def fuse(
        self,
        inputs: Iterable[FusionInput],
        *,
        options: FusionOptions,
    ) -> list[tuple[int, float]]:
        """Return fused ``(doc_id, score)`` pairs for the supplied channels."""
        ...


class RRFWeighter:
    """Adapter over :func:`fuse_weighted_rrf` operating on primitive tuples."""

    __slots__ = ("_invocations",)

    def __init__(self) -> None:
        """Initialize RRF weighter with zero invocation count."""
        self._invocations = 0

    def fuse(
        self,
        inputs: Iterable[FusionInput],
        *,
        options: FusionOptions,
    ) -> list[tuple[int, float]]:
        """Fuse multiple search channel results using weighted RRF.

        Parameters
        ----------
        inputs : Iterable[FusionInput]
            Search results from multiple channels to fuse.
        options : FusionOptions
            Fusion configuration (weights, k, etc.).

        Returns
        -------
        list[tuple[int, float]]
            Fused (doc_id, score) pairs, sorted by score descending.
        """
        self._invocations += 1
        converted: dict[str, list[SearchHit]] = {}
        for fusion_input in inputs:
            hits: list[SearchHit] = []
            for rank, (doc_id, score) in enumerate(fusion_input.candidates):
                hits.append(
                    SearchHit(
                        doc_id=str(int(doc_id)),
                        rank=rank,
                        score=float(score),
                        source=fusion_input.channel,
                        explain={"channel": fusion_input.channel},
                    )
                )
            converted[fusion_input.channel] = hits
        weights = dict(options.weights or {})
        docs, _ = fuse_weighted_rrf(
            converted,
            weights=weights,
            k=int(options.base),
            limit=int(options.k),
        )
        return [(int(doc.doc_id), float(doc.score)) for doc in docs]


__all__ = ["FusionInput", "FusionOptions", "FusionProtocol", "RRFWeighter"]
