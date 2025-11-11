"""Shared retrieval dataclasses for multi-stage pipelines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ChannelHit:
    """Score emitted by a retrieval channel prior to fusion."""

    doc_id: str
    score: float


@dataclass(slots=True, frozen=True)
class HybridResultDoc:
    """Final fused result produced by weighted RRF."""

    doc_id: str
    score: float


@dataclass(slots=True, frozen=True)
class HybridSearchResult:
    """Container for fused docs alongside explainability metadata."""

    docs: Sequence[HybridResultDoc]
    contributions: Mapping[str, list[tuple[str, int, float]]]
    channels: list[str]
    warnings: list[str]
    method: Mapping[str, object] | None = None


@dataclass(slots=True, frozen=True)
class StageSignals:
    """Signals gathered from a stage for downstream gating decisions."""

    candidate_count: int
    elapsed_ms: float
    best_score: float | None = None
    second_best_score: float | None = None

    def margin(self) -> float | None:
        """Return score gap between best and runner-up when available.

        Returns
        -------
        float | None
            Score margin or ``None`` when insufficient data exists.
        """
        if self.best_score is None or self.second_best_score is None:
            return None
        return self.best_score - self.second_best_score


@dataclass(slots=True, frozen=True)
class StageDecision:
    """Decision emitted by gating logic describing whether to run the stage."""

    should_run: bool
    reason: str
    notes: tuple[str, ...] = ()


__all__ = [
    "ChannelHit",
    "HybridResultDoc",
    "HybridSearchResult",
    "StageDecision",
    "StageSignals",
]
