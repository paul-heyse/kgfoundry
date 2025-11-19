"""Shared retrieval dataclasses for multi-stage pipelines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

ChunkId = int
FaissRow = int
Distance = float
FactoryString = str


@dataclass(slots=True, frozen=True)
class SearchHit:
    """Single retrieval hit emitted by FAISS/BM25/SPLADE/XTR stages.

    Attributes
    ----------
    doc_id : str
        Document/chunk identifier as a string.
    rank : int
        Rank position of this hit (1-based).
    score : float
        Relevance score for this hit. Higher scores indicate better matches.
    source : str
        Source channel identifier (e.g., "faiss", "bm25", "splade", "xtr").
    faiss_row : FaissRow | None, optional
        Optional FAISS row metadata. None if not from FAISS channel.
        Defaults to None.
    explain : Mapping[str, object], optional
        Optional explanation metadata for debugging and observability. Empty
        dictionary if no explanation is provided. Defaults to empty dictionary.
    """

    doc_id: str
    rank: int
    score: float
    source: str
    faiss_row: FaissRow | None = None
    explain: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SearchPoolRow:
    """Structured row recorded in evaluator pools.

    Attributes
    ----------
    query_id : str
        Query identifier for this pool row.
    channel : str
        Retrieval channel name (e.g., "faiss", "bm25", "splade").
    rank : int
        Rank position of this hit (1-based).
    chunk_id : ChunkId
        Chunk identifier for this hit.
    score : float
        Relevance score for this hit.
    reason : Mapping[str, object], optional
        Optional reason metadata explaining why this hit was included.
        Defaults to empty dictionary.
    """

    query_id: str
    channel: str
    rank: int
    chunk_id: ChunkId
    score: float
    reason: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class HybridResultDoc:
    """Final fused result produced by weighted RRF.

    Attributes
    ----------
    doc_id : str
        Document/chunk identifier as a string.
    score : float
        Fused relevance score after RRF combination. Higher scores indicate
        better matches.
    """

    doc_id: str
    score: float


@dataclass(slots=True, frozen=True)
class HybridSearchResult:
    """Container for fused docs alongside explainability metadata.

    Attributes
    ----------
    docs : Sequence[HybridResultDoc]
        Sequence of fused search results sorted by score descending.
    contributions : Mapping[str, Mapping[str, object]]
        Per-channel contribution metadata for explainability. Keys are channel
        names, values are channel-specific metadata dictionaries.
    channels : list[str]
        List of channel names that contributed to this result.
    warnings : list[str]
        List of warning messages encountered during search or fusion.
    method : Mapping[str, object] | None, optional
        Optional method metadata describing the fusion algorithm and parameters.
        None if method metadata is not available. Defaults to None.
    """

    docs: Sequence[HybridResultDoc]
    contributions: Mapping[str, Mapping[str, object]]
    channels: list[str]
    warnings: list[str]
    method: Mapping[str, object] | None = None


@dataclass(slots=True, frozen=True)
class StageSignals:
    """Signals gathered from a stage for downstream gating decisions.

    Attributes
    ----------
    candidate_count : int
        Number of candidates returned by this stage. Must be non-negative.
    elapsed_ms : float
        Elapsed time for this stage in milliseconds. Must be non-negative.
    best_score : float | None, optional
        Best (highest) relevance score from this stage. None if no candidates
        were returned. Defaults to None.
    second_best_score : float | None, optional
        Second-best relevance score from this stage. None if fewer than two
        candidates were returned. Defaults to None.
    """

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
    """Decision emitted by gating logic describing whether to run the stage.

    Attributes
    ----------
    should_run : bool
        Whether the stage should be executed based on gating logic.
    reason : str
        Human-readable reason string explaining the decision.
    notes : tuple[str, ...], optional
        Additional notes providing context for the decision. Empty tuple if no
        notes. Defaults to empty tuple.
    """

    should_run: bool
    reason: str
    notes: tuple[str, ...] = ()


__all__ = [
    "ChunkId",
    "Distance",
    "FactoryString",
    "FaissRow",
    "HybridResultDoc",
    "HybridSearchResult",
    "SearchHit",
    "SearchPoolRow",
    "StageDecision",
    "StageSignals",
]
