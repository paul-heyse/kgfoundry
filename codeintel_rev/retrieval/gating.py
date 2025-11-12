"""Adaptive gating helpers for multi-stage retrieval pipelines."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from codeintel_rev.retrieval.types import StageDecision, StageSignals


@dataclass(slots=True, frozen=True)
class StageGateConfig:
    """Configuration inputs for deciding whether to invoke a follow-up stage."""

    min_candidates: int = 40
    margin_threshold: float = 0.1
    budget_ms: int = 150
    enable_query_aware_budgets: bool = True
    default_depths: Mapping[str, int] = field(
        default_factory=lambda: {"semantic": 100, "bm25": 50, "splade": 50}
    )
    literal_depths: Mapping[str, int] = field(
        default_factory=lambda: {"semantic": 80, "bm25": 80, "splade": 30}
    )
    vague_depths: Mapping[str, int] = field(
        default_factory=lambda: {"semantic": 150, "bm25": 60, "splade": 80}
    )
    rrf_k_default: int = 60
    rrf_k_literal: int = 40
    rrf_k_vague: int = 90
    rm3_auto: bool = True
    rm3_min_len: int = 2
    rm3_max_len: int = 12
    rm3_enable_on_ambiguity: bool = True
    rm3_fb_docs: int = 10
    rm3_fb_terms: int = 10
    rm3_original_weight: float = 0.5
    code_token_patterns: tuple[str, ...] = (
        r"[A-Za-z_][A-Za-z0-9_]*",
        r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+",
        r"[a-z0-9_]+(?:\.[a-z0-9_]+)+",
        r"[A-Za-z0-9_\-/\.]+",
    )

_LITERAL_CODE_RATIO = 0.5
_LITERAL_DIGIT_RATIO = 0.2
_LITERAL_SYMBOL_RATIO = 0.03
_VAGUE_LENGTH_THRESHOLD = 5
_VAGUE_CODE_RATIO = 0.3
_AMBIGUITY_SHORT_LENGTH = 3
_AMBIGUITY_LOW_CODE_RATIO = 0.3
_AMBIGUITY_HIGH_OOV_RATIO = 0.6
_AMBIGUITY_SHORT_BOOST = 0.6
_AMBIGUITY_OOV_BOOST = 0.3
_AMBIGUITY_LITERAL_PENALTY = 0.4
_RM3_AMBIGUITY_THRESHOLD = 0.3
_AMBIGUITY_VAGUE_THRESHOLD = 0.5


def should_run_secondary_stage(
    signals: StageSignals,
    config: StageGateConfig,
) -> StageDecision:
    """Return a gating decision for a downstream stage based on upstream signals.

    Extended Summary
    ----------------
    This function implements adaptive gating logic for multi-stage retrieval pipelines,
    deciding whether to run expensive secondary stages (e.g., reranking, late interaction)
    based on upstream performance signals. It evaluates candidate count, elapsed time budget,
    and score margin to determine if the secondary stage would provide sufficient value.
    This prevents unnecessary computation when upstream results are already high-quality or
    when time budgets are exceeded, improving overall pipeline efficiency.

    Parameters
    ----------
    signals : StageSignals
        Performance signals from the upstream stage, including candidate count, elapsed
        time, and score distribution. Used to assess whether secondary stage is warranted.
    config : StageGateConfig
        Gating configuration specifying thresholds for candidate count, margin, and time
        budget. Defines the decision criteria for running the secondary stage.

    Returns
    -------
    StageDecision
        Decision object describing whether the stage should run and why. Contains
        should_run boolean, reason string, and optional notes explaining the decision.
        Reasons include: "no_candidates", "insufficient_candidates", "upstream_budget_exceeded",
        "high_margin", "within_budget".

    Notes
    -----
    Time complexity O(1) for decision logic. Space complexity O(1) aside from the
    StageDecision object. The function performs no I/O and has no side effects.
    Thread-safe as it operates on input data only. Decision logic prioritizes:
    1. Candidate availability (must have candidates)
    2. Time budget (must not exceed budget)
    3. Score margin (high margin suggests good results already)
    """
    notes: list[str] = []
    if signals.candidate_count <= 0:
        return StageDecision(should_run=False, reason="no_candidates")
    if signals.candidate_count < config.min_candidates:
        notes.append(f"{signals.candidate_count}/{config.min_candidates} candidates available")
        return StageDecision(should_run=False, reason="insufficient_candidates", notes=tuple(notes))

    if signals.elapsed_ms > config.budget_ms:
        notes.append(f"stage elapsed {signals.elapsed_ms:.1f}ms > budget {config.budget_ms}ms")
        return StageDecision(
            should_run=False, reason="upstream_budget_exceeded", notes=tuple(notes)
        )

    margin = signals.margin()
    if margin is not None and margin >= config.margin_threshold > 0:
        notes.append(f"margin {margin:.4f} >= threshold {config.margin_threshold:.4f}")
        return StageDecision(should_run=False, reason="high_margin", notes=tuple(notes))

    return StageDecision(should_run=True, reason="within_budget", notes=tuple(notes))


@dataclass(frozen=True)
class QueryProfile:
    """Query characteristics profile for adaptive retrieval gating.

    Extended Summary
    ----------------
    Encapsulates computed features of a search query used to make adaptive
    decisions about retrieval budgets and RM3 expansion. Features include
    token statistics, code-like patterns, and ambiguity indicators that help
    determine whether a query is literal (code-focused), vague (natural language),
    or ambiguous (unclear intent).

    Attributes
    ----------
    length : int
        Number of tokens in the query after tokenization.
    unique_ratio : float
        Ratio of unique tokens to total tokens (0.0 to 1.0). Higher values
        indicate more diverse vocabulary.
    code_token_ratio : float
        Ratio of tokens matching code-like patterns (0.0 to 1.0). Higher values
        suggest code-focused queries.
    digit_ratio : float
        Ratio of tokens containing digits (0.0 to 1.0). Higher values suggest
        numeric identifiers or literals.
    symbol_ratio : float
        Ratio of non-alphanumeric symbols in the query string (0.0 to 1.0).
        Higher values suggest code syntax or special characters.
    oov_ratio : float
        Out-of-vocabulary ratio (1.0 - code_token_ratio). Higher values suggest
        natural language terms.
    looks_literal : bool
        True if query appears code-focused (high code_token_ratio, digit_ratio,
        or symbol_ratio).
    looks_vague : bool
        True if query appears vague or natural language (short, low code_token_ratio).
    ambiguity_score : float
        Ambiguity score (0.0 to 1.0). Higher values indicate unclear query intent.
        Computed from length, code_token_ratio, and oov_ratio.
    """

    length: int
    unique_ratio: float
    code_token_ratio: float
    digit_ratio: float
    symbol_ratio: float
    oov_ratio: float
    looks_literal: bool
    looks_vague: bool
    ambiguity_score: float


@dataclass(frozen=True)
class BudgetDecision:
    """Retrieval budget decision for multi-stage search pipelines.

    Extended Summary
    ----------------
    Encapsulates adaptive budget decisions for hybrid retrieval pipelines.
    Determines how many results to fetch from each retrieval channel (semantic,
    BM25, SPLADE) and whether to enable RM3 query expansion. Decisions are
    based on query profile characteristics to optimize recall and latency.

    Attributes
    ----------
    per_channel_depths : dict[str, int]
        Dictionary mapping channel names ("semantic", "bm25", "splade") to
        result depths (number of results to fetch). Higher depths improve recall
        but increase latency.
    rrf_k : int
        Reciprocal Rank Fusion (RRF) parameter controlling how many results to
        combine from all channels. Higher values improve recall but increase
        computation.
    rm3_enabled : bool
        Whether RM3 query expansion is enabled for this query. RM3 improves
        recall for ambiguous queries but adds latency.
    """

    per_channel_depths: dict[str, int]
    rrf_k: int
    rm3_enabled: bool


_SYMBOL_RE = re.compile(r"[^A-Za-z0-9_\s]")
_DIGIT_RE = re.compile(r"\d")


def _tokenize(query: str) -> list[str]:
    return [token for token in re.split(r"\s+", query.strip()) if token]


def _code_like_count(tokens: list[str], patterns: tuple[str, ...]) -> int:
    compiled = [re.compile(pattern) for pattern in patterns]
    count = 0
    for token in tokens:
        if any(regex.fullmatch(token) for regex in compiled):
            count += 1
    return count


def analyze_query(query: str, cfg: StageGateConfig) -> QueryProfile:
    """Analyze query characteristics to build a query profile.

    Extended Summary
    ----------------
    Tokenizes the query and computes statistical features (token counts, ratios,
    pattern matches) to determine query characteristics. Classifies queries as
    literal (code-focused), vague (natural language), or ambiguous based on
    heuristics. The profile is used to make adaptive retrieval budget decisions.

    Parameters
    ----------
    query : str
        Search query string to analyze.
    cfg : StageGateConfig
        Configuration containing code token patterns and thresholds for
        classification.

    Returns
    -------
    QueryProfile
        Query profile with computed features (length, ratios, flags, ambiguity
        score) used for adaptive gating decisions.

    Notes
    -----
    Time O(n) where n is query length. Tokenization uses whitespace splitting.
    Code token matching uses regex patterns. Classification heuristics are
    deterministic and fast.
    """
    tokens = _tokenize(query)
    length = len(tokens)
    unique_ratio = (len(set(tokens)) / length) if length else 0.0
    code_like = _code_like_count(tokens, cfg.code_token_patterns)
    code_token_ratio = (code_like / length) if length else 0.0
    digit_ratio = (
        (sum(1 for token in tokens if _DIGIT_RE.search(token)) / length) if length else 0.0
    )
    symbol_ratio = len(_SYMBOL_RE.findall(query)) / max(1, len(query))
    oov_ratio = 1.0 - code_token_ratio

    looks_literal = (
        (code_token_ratio > _LITERAL_CODE_RATIO)
        or (digit_ratio > _LITERAL_DIGIT_RATIO)
        or (symbol_ratio > _LITERAL_SYMBOL_RATIO)
    )
    looks_vague = not looks_literal and (
        length <= _VAGUE_LENGTH_THRESHOLD and code_token_ratio < _VAGUE_CODE_RATIO
    )

    ambiguity = 0.0
    if length <= _AMBIGUITY_SHORT_LENGTH and code_token_ratio < _AMBIGUITY_LOW_CODE_RATIO:
        ambiguity += _AMBIGUITY_SHORT_BOOST
    if oov_ratio > _AMBIGUITY_HIGH_OOV_RATIO:
        ambiguity += _AMBIGUITY_OOV_BOOST
    if looks_literal:
        ambiguity -= _AMBIGUITY_LITERAL_PENALTY
    ambiguity = max(0.0, min(1.0, ambiguity))

    return QueryProfile(
        length=length,
        unique_ratio=unique_ratio,
        code_token_ratio=code_token_ratio,
        digit_ratio=digit_ratio,
        symbol_ratio=symbol_ratio,
        oov_ratio=oov_ratio,
        looks_literal=looks_literal,
        looks_vague=looks_vague,
        ambiguity_score=ambiguity,
    )


def decide_budgets(profile: QueryProfile, cfg: StageGateConfig) -> BudgetDecision:
    """Decide retrieval budgets based on query profile.

    Extended Summary
    ----------------
    Determines adaptive retrieval budgets (channel depths, RRF k, RM3 enablement)
    based on query profile characteristics. Uses different budget presets for
    literal queries (code-focused), vague queries (natural language), and default
    queries. RM3 expansion is enabled for queries within length bounds and
    ambiguity thresholds.

    Parameters
    ----------
    profile : QueryProfile
        Query profile with computed characteristics (length, ratios, flags).
    cfg : StageGateConfig
        Configuration containing budget presets and RM3 thresholds.

    Returns
    -------
    BudgetDecision
        Budget decision with per-channel depths, RRF k parameter, and RM3
        enablement flag. Returns default budgets if query-aware budgets are
        disabled in config.
    """
    if not cfg.enable_query_aware_budgets:
        return BudgetDecision(dict(cfg.default_depths), cfg.rrf_k_default, cfg.rm3_auto)

    if profile.looks_literal:
        depths = dict(cfg.literal_depths)
        rrf_k = cfg.rrf_k_literal
    elif profile.looks_vague or profile.ambiguity_score >= _AMBIGUITY_VAGUE_THRESHOLD:
        depths = dict(cfg.vague_depths)
        rrf_k = cfg.rrf_k_vague
    else:
        depths = dict(cfg.default_depths)
        rrf_k = cfg.rrf_k_default

    rm3_enabled = bool(
        cfg.rm3_auto
        and cfg.rm3_min_len <= profile.length <= cfg.rm3_max_len
        and (
            profile.ambiguity_score >= _RM3_AMBIGUITY_THRESHOLD
            or cfg.rm3_enable_on_ambiguity
        )
    )

    return BudgetDecision(depths, rrf_k, rm3_enabled)


def describe_budget_decision(profile: QueryProfile, decision: BudgetDecision) -> dict[str, object]:
    """Serialize query profile and budget decision to a dictionary.

    Extended Summary
    ----------------
    Converts query profile and budget decision into a dictionary format suitable
    for logging, metrics, or API responses. Includes rounded ratios and all
    decision parameters for observability and debugging.

    Parameters
    ----------
    profile : QueryProfile
        Query profile with computed characteristics.
    decision : BudgetDecision
        Budget decision with channel depths, RRF k, and RM3 flag.

    Returns
    -------
    dict[str, object]
        Dictionary containing query profile fields (length, ratios rounded to
        3 decimals) and budget decision fields (per_channel_depths, rrf_k,
        rm3_enabled). Used for logging and observability.
    """
    return {
        "length": profile.length,
        "unique_ratio": round(profile.unique_ratio, 3),
        "code_token_ratio": round(profile.code_token_ratio, 3),
        "digit_ratio": round(profile.digit_ratio, 3),
        "symbol_ratio": round(profile.symbol_ratio, 3),
        "oov_ratio": round(profile.oov_ratio, 3),
        "looks_literal": profile.looks_literal,
        "looks_vague": profile.looks_vague,
        "ambiguity_score": round(profile.ambiguity_score, 3),
        "per_channel_depths": decision.per_channel_depths,
        "rrf_k": decision.rrf_k,
        "rm3_enabled": decision.rm3_enabled,
    }


__all__ = [
    "BudgetDecision",
    "QueryProfile",
    "StageGateConfig",
    "analyze_query",
    "decide_budgets",
    "describe_budget_decision",
    "should_run_secondary_stage",
]
