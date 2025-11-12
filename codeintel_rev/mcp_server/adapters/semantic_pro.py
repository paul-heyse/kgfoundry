"""Two-stage semantic search (CodeRank → optional WARP → optional reranker)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, TypedDict, cast

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.io.hybrid_search import (
    ChannelHit,
    HybridSearchOptions,
    HybridSearchTuning,
)
from codeintel_rev.io.rerank_coderankllm import CodeRankListwiseReranker
from codeintel_rev.io.warp_engine import WarpEngine, WarpUnavailableError
from codeintel_rev.mcp_server.common.observability import Observation, observe_duration
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    Finding,
    MethodInfo,
    ScopeIn,
    StageInfo,
)
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.rerank.base import RerankRequest, RerankResult, ScoredDoc
from codeintel_rev.rerank.xtr import XTRReranker
from codeintel_rev.retrieval.gating import StageGateConfig, should_run_secondary_stage
from codeintel_rev.retrieval.telemetry import (
    StageTiming,
    record_stage_decision,
    record_stage_metric,
    track_stage,
)
from codeintel_rev.retrieval.types import (
    HybridResultDoc,
    HybridSearchResult,
    StageDecision,
    StageSignals,
)
from kgfoundry_common.errors import EmbeddingError, VectorSearchError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext
    from codeintel_rev.config.settings import RerankConfig, XTRConfig
    from codeintel_rev.io.xtr_manager import XTRIndex

SNIPPET_PREVIEW_CHARS = 500
COMPONENT_NAME = "codeintel_mcp"
RERANK_STAGE_NAME = "coderank_llm"
LOGGER = get_logger(__name__)


class RerankOptionPayload(TypedDict, total=False):
    """User-facing payload for overruling rerank behavior."""

    enabled: bool
    top_k: int
    provider: str
    explain: bool


class SemanticProOptions(TypedDict, total=False):
    """User-facing options for semantic_pro retrieval."""

    use_coderank: bool
    use_warp: bool
    use_reranker: bool
    stage_weights: dict[str, float]
    explain: bool
    xtr_k: int
    rerank: RerankOptionPayload


@dataclass(frozen=True)
class RerankRuntimeOptions:
    """Runtime overrides for optional reranker stage."""

    enabled: bool = False
    top_k: int | None = None
    provider: str | None = None
    explain: bool | None = None


@dataclass(slots=True, frozen=True)
class RerankPlan:
    """Concrete rerank execution plan derived from settings + overrides."""

    enabled: bool
    top_k: int
    provider: str
    explain: bool
    reason: str | None = None


@dataclass(frozen=True)
class SemanticProRuntimeOptions:
    """Internal immutable representation of semantic_pro options."""

    use_coderank: bool = True
    use_warp: bool = True
    use_reranker: bool = False
    stage_weights: dict[str, float] = field(default_factory=dict)
    explain: bool = True
    xtr_k: int | None = None
    rerank: RerankRuntimeOptions | None = None


WideSearchHandle = tuple[Future["WarpOutcome"], ThreadPoolExecutor]


@dataclass(slots=True, frozen=True)
class StageOnePlan:
    """Container for Stage-1 orchestration inputs to reduce argument lists."""

    context: ApplicationContext
    query: str
    candidates: Sequence[tuple[int, float]]
    options: SemanticProRuntimeOptions
    coderank_stage: StageTiming
    wide_handle: WideSearchHandle | None


@dataclass(slots=True, frozen=True)
class HydrationPlan:
    """Hydration plus rerank inputs passed as a cohesive plan."""

    context: ApplicationContext
    query: str
    fused: HybridSearchResult
    scope: ScopeIn | None
    effective_limit: int
    options: SemanticProRuntimeOptions
    observation: Observation


@dataclass(slots=True, frozen=True)
class HydrationOutcome:
    """Result of DuckDB hydration and optional LLM rerank."""

    records: list[dict]
    timings: list[StageTiming]


def build_runtime_options(
    options: SemanticProOptions | None,
) -> SemanticProRuntimeOptions:
    """Normalize user-supplied options into an immutable dataclass.

    Extended Summary
    ----------------
    This function converts user-facing TypedDict options into an internal immutable
    dataclass representation with defaults applied. It serves as the boundary between
    the MCP server's request schema and the internal retrieval pipeline, ensuring
    type safety and providing sensible defaults for optional configuration. The
    function is called once per semantic_pro request to prepare runtime options
    for the two-stage retrieval pipeline (CodeRank → optional WARP → optional reranker).

    Parameters
    ----------
    options : SemanticProOptions | None
        User-supplied options dictionary. May be ``None`` to use all defaults.
        Keys include: ``use_coderank`` (default True), ``use_warp`` (default True),
        ``use_reranker`` (default False), ``stage_weights`` (default empty dict),
        ``explain`` (default True). Missing keys are filled with defaults.

    Returns
    -------
    SemanticProRuntimeOptions
        Immutable dataclass instance with normalized options. All fields have
        defaults applied, ensuring the returned value is always valid for pipeline
        execution.

    Notes
    -----
    Time complexity O(1). No I/O or side effects. The function performs a shallow
    copy of stage_weights to ensure immutability of the returned dataclass.

    Examples
    --------
    >>> opts = build_runtime_options(None)
    >>> opts.use_coderank
    True
    >>> opts.use_warp
    True
    >>> opts.use_reranker
    False
    >>> user_opts = {"use_warp": False, "use_reranker": True}
    >>> opts = build_runtime_options(user_opts)
    >>> opts.use_warp
    False
    >>> opts.use_reranker
    True
    """
    if options is None:
        return SemanticProRuntimeOptions()
    xtr_k_value = options.get("xtr_k")
    parsed_xtr_k = None
    if xtr_k_value is not None:
        try:
            parsed_xtr_k = int(xtr_k_value)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Ignoring non-numeric xtr_k override",
                extra={"value": xtr_k_value},
            )
    rerank_payload = options.get("rerank")
    rerank_runtime = None
    if isinstance(rerank_payload, dict):
        rerank_runtime = RerankRuntimeOptions(
            enabled=bool(rerank_payload.get("enabled", True)),
            top_k=_coerce_positive_int(rerank_payload.get("top_k")),
            provider=rerank_payload.get("provider"),
            explain=rerank_payload.get("explain"),
        )
    return SemanticProRuntimeOptions(
        use_coderank=options.get("use_coderank", True),
        use_warp=options.get("use_warp", True),
        use_reranker=options.get("use_reranker", False),
        stage_weights=dict(options.get("stage_weights", {})),
        explain=options.get("explain", True),
        xtr_k=parsed_xtr_k,
        rerank=rerank_runtime,
    )


def _summarize_options(options: SemanticProRuntimeOptions) -> dict[str, object]:
    summary: dict[str, object] = {
        "use_coderank": options.use_coderank,
        "use_warp": options.use_warp,
        "use_reranker": options.use_reranker,
    }
    if options.stage_weights:
        summary["stage_weights"] = options.stage_weights
    if options.xtr_k is not None:
        summary["xtr_k"] = options.xtr_k
    return summary


async def semantic_search_pro(
    context: ApplicationContext,
    *,
    query: str,
    limit: int,
    options: SemanticProOptions | None = None,
) -> AnswerEnvelope:
    """Execute the two-stage semantic search pipeline (CodeRank → optional WARP → optional reranker).

    Extended Summary
    ----------------
    This async function orchestrates the semantic_pro retrieval pipeline, which combines
    CodeRank dense vector search with optional WARP late-interaction reranking and optional
    CodeRankLLM listwise reranking. The function normalizes options, resolves scope filters,
    executes stages conditionally based on gating logic and user preferences, fuses results
    using weighted RRF, hydrates metadata from DuckDB, and assembles the final AnswerEnvelope
    with findings, explanations, and telemetry. It is the primary entry point for semantic
    code search in the MCP server, providing high-quality ranked results with explainability
    and performance budgets.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings, paths, and initialized components
        (FAISS managers, embedders, catalog). Must have valid CodeRank FAISS index
        and catalog configured.
    query : str
        Natural language search query. Will be embedded using CodeRank embedder
        and optionally processed by WARP for late-interaction scoring.
    limit : int
        Maximum number of results to return. Will be clamped to the configured
        max_results limit. Must be positive.
    options : SemanticProOptions | None, optional
        User-supplied pipeline options. Controls which stages run (use_coderank,
        use_warp, use_reranker), fusion weights (stage_weights), and whether to
        include explanations (explain). Defaults to None (all defaults applied).

    Returns
    -------
    AnswerEnvelope
        Search results envelope containing:
        - ``answer``: Human-readable summary string
        - ``findings``: List of Finding objects with location, snippet, score, and optional why
        - ``method``: Retrieval metadata including channels used, coverage, and stage timings
        - ``limits``: Optional list of warnings about budget overruns or limit clamping
        - ``scope``: Optional scope filters that were applied
        - ``query_kind``: Always "semantic_pro"
        - ``confidence``: Float between 0.0 and 1.0

    Raises
    ------
    VectorSearchError
        If limit is not positive, CodeRank FAISS index is missing, search fails,
        or DuckDB hydration fails. All errors include Problem Details context.

    Notes
    -----
    Time complexity dominated by I/O: embedding (O(1) queries), FAISS search (O(k log n)
    where k is fanout and n is index size), WARP reranking (O(m * d) where m is candidates
    and d is sequence length), fusion (O(n * c) where n is hits and c is channels), DuckDB
    hydration (O(r) where r is result count), optional reranking (O(r * model_latency)).
    The function performs extensive I/O (FAISS, DuckDB, optional GPU models) and is not
    thread-safe (uses context managers and shared state). Performance budgets are tracked
    per stage and violations are reported in the limits field. The function uses asyncio
    to offload synchronous work to a thread pool. Note that EmbeddingError may be propagated
    from downstream functions (e.g., CodeRank embedder failures) but is wrapped as VectorSearchError
    at the API boundary.

    Examples
    --------
    >>> # Minimal example (requires ApplicationContext setup)
    >>> # from codeintel_rev.app.config_context import ApplicationContext
    >>> # context = ApplicationContext(...)
    >>> # results = await semantic_search_pro(context, query="vector store", limit=10)
    >>> # assert results["query_kind"] == "semantic_pro"
    >>> # assert len(results["findings"]) <= 10
    """
    if limit <= 0:
        msg = f"limit must be positive, got {limit}"
        raise VectorSearchError(msg)
    runtime_options = build_runtime_options(options)
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    return await asyncio.to_thread(
        _semantic_search_pro_sync,
        context,
        query,
        limit,
        scope,
        runtime_options,
    )


def _semantic_search_pro_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    scope: ScopeIn | None,
    options: SemanticProRuntimeOptions,
) -> AnswerEnvelope:
    if not options.use_coderank:
        msg = "CodeRank stage must be enabled; disable warp/reranker instead if needed."
        raise VectorSearchError(msg)

    start_time = perf_counter()
    stage_timings: list[StageTiming] = []
    limits: list[str] = []
    with observe_duration("semantic_search_pro", COMPONENT_NAME) as observation:
        effective_limit = _clamp_limit(
            limit,
            context.settings.limits.max_results,
            limits,
        )
        wide_handle = _maybe_schedule_xtr_wide(
            context=context,
            query=query,
            limit=effective_limit,
            options=options,
        )
        coderank_fanout = max(
            effective_limit,
            effective_limit * context.settings.limits.semantic_overfetch_multiplier,
        )
        coderank_hits, coderank_stage = _timed_coderank_stage(
            context=context,
            query=query,
            fanout=coderank_fanout,
            observation=observation,
        )
        stage_timings.append(coderank_stage)

        warp_outcome = _resolve_stage_one_outcome(
            StageOnePlan(
                context=context,
                query=query,
                candidates=tuple(coderank_hits),
                options=options,
                coderank_stage=coderank_stage,
                wide_handle=wide_handle,
            )
        )
        if warp_outcome.timing is not None:
            stage_timings.append(warp_outcome.timing)

        fused = _run_fusion_stage(
            context=context,
            request=FusionRequest(
                query=query,
                coderank_hits=coderank_hits,
                warp_hits=warp_outcome.hits,
                warp_channel=warp_outcome.channel,
                effective_limit=effective_limit,
                weights=_merge_rrf_weights(
                    context.settings.index.rrf_weights, options.stage_weights
                ),
                faiss_k=coderank_fanout,
                nprobe=context.settings.index.faiss_nprobe,
            ),
            stage_timings=stage_timings,
        )
        fused, rerank_metadata = _maybe_apply_rerank_stage(
            context=context,
            query=query,
            fused=fused,
            options=options,
            stage_timings=stage_timings,
        )

        if not fused.docs:
            observation.mark_success()
            return _make_envelope(
                answer=f"No results found for: {query}",
                findings=[],
                extras=_assemble_extras(
                    method=_build_method(
                        MethodContext(
                            findings_count=0,
                            requested_limit=limit,
                            effective_limit=effective_limit,
                            start_time=start_time,
                            channels=fused.channels,
                            stages=tuple(stage_timings),
                            notes=tuple(warp_outcome.notes),
                            explainability=_build_method_explainability(
                                warp_outcome.explainability
                            ),
                            rerank=rerank_metadata,
                            hybrid_method=(
                                cast("MethodInfo", dict(fused.method)) if fused.method else None
                            ),
                        )
                    ),
                    limits=limits + fused.warnings,
                    scope=scope,
                ),
            )

        hydration_result = _hydrate_and_rerank_records(
            HydrationPlan(
                context=context,
                query=query,
                fused=fused,
                scope=scope,
                effective_limit=effective_limit,
                options=options,
                observation=observation,
            )
        )
        stage_timings.extend(hydration_result.timings)

        findings = _build_findings(
            records=hydration_result.records,
            docs=fused.docs,
            contribution_map=fused.contributions,
            explain=options.explain,
        )
        merge_explainability_into_findings(findings, warp_outcome.explainability)
        observation.mark_success()
        _append_budget_notes(COMPONENT_NAME, stage_timings, limits)
        return _make_envelope(
            answer=f"Found {len(findings)} semantic_pro results for: {query}",
            findings=findings,
            extras=_assemble_extras(
                method=_build_method(
                    MethodContext(
                        findings_count=len(findings),
                        requested_limit=limit,
                        effective_limit=effective_limit,
                        start_time=start_time,
                        channels=fused.channels,
                        stages=tuple(stage_timings),
                        notes=tuple(warp_outcome.notes),
                        explainability=_build_method_explainability(warp_outcome.explainability),
                        rerank=rerank_metadata,
                        hybrid_method=(
                            cast("MethodInfo", dict(fused.method)) if fused.method else None
                        ),
                    )
                ),
                limits=limits + fused.warnings,
                scope=scope,
            ),
        )


def _run_coderank_stage(
    *,
    context: ApplicationContext,
    query: str,
    fanout: int,
    observation: Observation,
) -> list[tuple[int, float]]:
    if not context.paths.coderank_faiss_index.exists():
        observation.mark_error()
        msg = "CodeRank FAISS index not found; build it via `python coderank.py build-index`."
        raise VectorSearchError(
            msg,
            context={"coderank_faiss_index": str(context.paths.coderank_faiss_index)},
        )

    try:
        query_vec = context.vllm_client.embed_batch([query])
    except Exception as exc:
        observation.mark_error()
        msg = f"CodeRank embedding failed: {exc}"
        raise EmbeddingError(
            msg,
            context={
                "model_id": context.settings.vllm.model,
                "mode": context.settings.vllm.run.mode,
            },
        ) from exc

    try:
        faiss_mgr = context.get_coderank_faiss_manager(query_vec.shape[1])
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        observation.mark_error()
        msg = "Failed to load CodeRank FAISS index"
        raise VectorSearchError(msg, cause=exc) from exc

    try:
        distances, ids = faiss_mgr.search(
            query_vec,
            k=max(1, int(fanout)),
            nprobe=context.settings.index.faiss_nprobe,
        )
    except RuntimeError as exc:
        observation.mark_error()
        msg = "CodeRank FAISS search failed"
        raise VectorSearchError(msg, cause=exc) from exc

    chunk_ids = ids[0].tolist()
    scores = distances[0].tolist()
    hits: list[tuple[int, float]] = [
        (int(chunk_id), float(score))
        for chunk_id, score in zip(chunk_ids, scores, strict=False)
        if chunk_id >= 0
    ]
    return hits


def _timed_coderank_stage(
    *,
    context: ApplicationContext,
    query: str,
    fanout: int,
    observation: Observation,
) -> tuple[list[tuple[int, float]], StageTiming]:
    with track_stage(
        "coderank_ann",
        budget_ms=context.settings.coderank.budget_ms,
    ) as timer:
        hits = _run_coderank_stage(
            context=context,
            query=query,
            fanout=fanout,
            observation=observation,
        )
    return hits, timer.snapshot()


def _maybe_run_warp(
    *,
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
    options: SemanticProRuntimeOptions,
    coderank_stage: StageTiming,
) -> WarpOutcome:
    should_run, notes = _should_execute_stage_two(
        context=context,
        candidates=candidates,
        options=options,
        coderank_stage=coderank_stage,
    )
    if not should_run:
        return WarpOutcome(hits=[], notes=notes, timing=None, explainability=())
    return _execute_stage_two(
        context=context,
        query=query,
        candidates=candidates,
        options=options,
        base_notes=notes,
    )


def _should_execute_stage_two(
    *,
    context: ApplicationContext,
    candidates: list[tuple[int, float]],
    options: SemanticProRuntimeOptions,
    coderank_stage: StageTiming,
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    stage_name = "stage_b"
    if not candidates:
        notes.append("No CodeRank candidates; skipping Stage-B.")
        record_stage_decision(
            COMPONENT_NAME,
            stage_name,
            decision=StageDecision(should_run=False, reason="no_candidates"),
        )
        return False, notes
    if not options.use_warp:
        notes.append("Stage-B disabled via request option.")
        record_stage_decision(
            COMPONENT_NAME,
            stage_name,
            decision=StageDecision(should_run=False, reason="disabled_option"),
        )
        return False, notes
    stage_available = context.settings.warp.enabled or context.settings.xtr.enable
    if not stage_available:
        notes.append("WARP/XTR disabled via configuration flag.")
        record_stage_decision(
            COMPONENT_NAME,
            stage_name,
            decision=StageDecision(should_run=False, reason="disabled_config"),
        )
        return False, notes
    signals = StageSignals(
        candidate_count=len(candidates),
        elapsed_ms=coderank_stage.duration_ms,
        best_score=candidates[0][1] if candidates else None,
        second_best_score=candidates[1][1] if len(candidates) > 1 else None,
    )
    gate_config = StageGateConfig(
        min_candidates=context.settings.coderank.min_stage2_candidates,
        margin_threshold=context.settings.coderank.min_stage2_margin,
        budget_ms=context.settings.coderank.budget_ms,
    )
    decision = should_run_secondary_stage(signals, gate_config)
    record_stage_decision(COMPONENT_NAME, stage_name, decision=decision)
    if not decision.should_run:
        notes.append(f"Stage-B gating: {decision.reason}")
        notes.extend(decision.notes)
        return False, notes
    return True, notes


def _execute_stage_two(
    *,
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
    options: SemanticProRuntimeOptions,
    base_notes: list[str],
) -> WarpOutcome:
    with track_stage(
        "warp_late_interaction",
        budget_ms=context.settings.warp.budget_ms,
    ) as warp_timer:
        hits, warp_notes, explain_payload, channel = _run_warp_stage(
            context=context,
            query=query,
            candidates=candidates,
            options=options,
        )
    notes = [*base_notes, *warp_notes]
    outcome = WarpOutcome(
        hits=hits,
        notes=notes,
        timing=warp_timer.snapshot(),
        explainability=tuple(explain_payload),
        channel=channel,
    )
    record_stage_decision(
        COMPONENT_NAME,
        channel,
        decision=StageDecision(should_run=True, reason="executed"),
    )
    return outcome


def _run_fusion_stage(
    *,
    context: ApplicationContext,
    request: FusionRequest,
    stage_timings: list[StageTiming],
) -> HybridSearchResult:
    engine = context.get_hybrid_engine()
    total_limit = max(
        request.effective_limit,
        request.effective_limit * context.settings.limits.semantic_overfetch_multiplier,
    )
    with track_stage("fusion_rrf") as fusion_timer:
        fused = engine.search(
            request.query,
            semantic_hits=request.coderank_hits,
            limit=total_limit,
            options=HybridSearchOptions(
                extra_channels=_build_extra_channels(request.warp_hits, request.warp_channel),
                weights=request.weights,
                tuning=HybridSearchTuning(k=request.faiss_k, nprobe=request.nprobe),
            ),
        )
    stage_timings.append(fusion_timer.snapshot())
    return fused


def _maybe_apply_rerank_stage(
    *,
    context: ApplicationContext,
    query: str,
    fused: HybridSearchResult,
    options: SemanticProRuntimeOptions,
    stage_timings: list[StageTiming],
) -> tuple[HybridSearchResult, dict[str, object] | None]:
    plan = _build_rerank_plan(context.settings.rerank, options.rerank)
    metadata: dict[str, object] = {
        "provider": plan.provider,
        "top_k": plan.top_k,
        "enabled": False,
    }
    timeline = current_timeline()
    if not plan.enabled:
        metadata["reason"] = plan.reason or "disabled"
        _emit_rerank_decision(timeline, metadata)
        return fused, metadata

    reranker = _resolve_reranker(context, plan.provider)
    if reranker is None:
        metadata["reason"] = "capability_off"
        _emit_rerank_decision(timeline, metadata)
        return fused, metadata

    scored_docs = [
        ScoredDoc(doc_id=_safe_int(doc.doc_id), score=float(doc.score)) for doc in fused.docs
    ]
    if not scored_docs:
        metadata["reason"] = "no_candidates"
        _emit_rerank_decision(timeline, metadata)
        return fused, metadata

    effective_top_k = min(plan.top_k, len(scored_docs))
    metadata.update(
        {
            "enabled": True,
            "candidates": len(scored_docs),
            "top_k": effective_top_k,
        }
    )
    _emit_rerank_decision(timeline, metadata)
    if timeline is not None:
        timeline.event(
            "rerank.start",
            "rerank",
            attrs={"provider": plan.provider, "top_k": effective_top_k},
        )
    with track_stage("rerank_xtr") as rerank_timer:
        results = reranker.rescore(
            RerankRequest(
                query=query,
                docs=scored_docs,
                top_k=effective_top_k,
                explain=plan.explain,
            )
        )
    stage_timings.append(rerank_timer.snapshot())
    if timeline is not None:
        timeline.event(
            "rerank.end",
            "rerank",
            attrs={"provider": plan.provider, "returned": len(results)},
        )
    reordered = _reorder_docs(fused, results)
    metadata["reordered"] = reordered.changes
    return reordered.result, metadata


@dataclass(slots=True, frozen=True)
class _RerankOutcome:
    result: HybridSearchResult
    changes: int


def _reorder_docs(
    fused: HybridSearchResult,
    results: Sequence[RerankResult],
) -> _RerankOutcome:
    doc_map = {_safe_int(doc.doc_id): doc for doc in fused.docs}
    score_map = {res.doc_id: res.score for res in results}
    ordered_ids: list[int] = []
    seen: set[int] = set()
    for res in results:
        if res.doc_id in seen or res.doc_id not in doc_map:
            continue
        ordered_ids.append(res.doc_id)
        seen.add(res.doc_id)
    for doc in fused.docs:
        cid = _safe_int(doc.doc_id)
        if cid not in seen:
            ordered_ids.append(cid)
            seen.add(cid)
    updated_docs = [
        HybridResultDoc(
            doc_id=doc_map[cid].doc_id,
            score=score_map.get(cid, doc_map[cid].score),
        )
        for cid in ordered_ids
    ]
    original_positions = {_safe_int(doc.doc_id): idx for idx, doc in enumerate(fused.docs)}
    new_positions = {cid: idx for idx, cid in enumerate(ordered_ids)}
    changes = sum(
        1
        for cid, original_idx in original_positions.items()
        if new_positions.get(cid, original_idx) != original_idx
    )
    updated_result = HybridSearchResult(
        docs=tuple(updated_docs),
        contributions=fused.contributions,
        channels=fused.channels,
        warnings=fused.warnings,
        method=fused.method,
    )
    return _RerankOutcome(result=updated_result, changes=changes)


def _emit_rerank_decision(timeline: Timeline | None, attrs: dict[str, object]) -> None:
    if timeline is None:
        return
    timeline.event("rerank.decision", "rerank", attrs=attrs)


def _build_rerank_plan(
    config: RerankConfig,
    override: RerankRuntimeOptions | None,
) -> RerankPlan:
    enabled = override.enabled if override is not None else config.enabled
    reason: str | None = None
    if not enabled:
        reason = "disabled_option" if override is not None else "disabled_config"
    top_k_override = override.top_k if override is not None else None
    explain_override = override.explain if override is not None else None
    top_k = top_k_override or config.top_k or 50
    explain = bool(explain_override) if explain_override is not None else config.explain
    return RerankPlan(
        enabled=enabled,
        top_k=max(1, top_k),
        provider="xtr",
        explain=explain,
        reason=reason,
    )


def _resolve_reranker(
    context: ApplicationContext,
    provider: str,
) -> XTRReranker | None:
    if provider != "xtr" or not context.settings.xtr.enable:
        return None
    try:
        index = context.get_xtr_index()
    except RuntimeUnavailableError:
        return None
    if index is None or not index.ready:
        return None
    return XTRReranker(index)


def _maybe_schedule_xtr_wide(
    *,
    context: ApplicationContext,
    query: str,
    limit: int,
    options: SemanticProRuntimeOptions,
) -> WideSearchHandle | None:
    cfg = context.settings.xtr
    if not (options.use_warp and cfg.enable and getattr(cfg, "mode", "narrow") == "wide"):
        return None
    try:
        index = context.get_xtr_index()
    except RuntimeUnavailableError as exc:
        LOGGER.info(
            "XTR wide-stage unavailable",
            extra={"detail": exc.context.get("detail") if hasattr(exc, "context") else str(exc)},
        )
        return None
    if index is None or not index.ready:
        return None
    k = _calculate_xtr_k(limit, cfg, options)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        _run_xtr_wide_stage,
        index,
        query,
        k,
        explain=options.explain,
        budget_ms=context.settings.warp.budget_ms,
    )
    return future, executor


def _resolve_stage_one_outcome(plan: StageOnePlan) -> WarpOutcome:
    """Resolve Stage-1 orchestration outcome from a StageOnePlan.

    Extended Summary
    ----------------
    This function orchestrates the resolution of Stage-1 search outcomes, coordinating
    between wide-mode XTR search (if initiated) and narrow-mode Stage-2 execution.
    It evaluates whether Stage-2 should run based on candidate quality and options,
    handles wide search futures, and falls back to narrow mode when wide search fails
    or is not available. The function manages executor lifecycle and aggregates notes
    from both stages, producing a unified WarpOutcome for downstream processing.

    Parameters
    ----------
    plan : StageOnePlan
        Container holding Stage-1 orchestration inputs including context, query,
        candidates, options, coderank timing, and optional wide search handle.
        The plan encapsulates all state needed to resolve the search outcome.

    Returns
    -------
    WarpOutcome
        Outcome describing hits, notes, timing, explainability, and channel.
        The outcome aggregates results from wide search (if successful) or Stage-2
        execution, with notes from both stages combined.

    Notes
    -----
    Time complexity depends on search mode: O(1) if Stage-2 is skipped, O(C * T * D)
    for narrow mode where C is candidate count, T is tokens, D is embedding dimension.
    Space complexity O(k) for results where k is the effective limit. The function
    performs I/O via wide search future and Stage-2 execution. Executor shutdown is
    best-effort (wait=False) to avoid blocking. Thread-safe for concurrent plan
    processing. Handles wide search failures gracefully by falling back to narrow mode.
    """
    context = plan.context
    query = plan.query
    candidates = list(plan.candidates)
    options = plan.options
    coderank_stage = plan.coderank_stage
    wide_handle = plan.wide_handle
    query = plan.query
    should_run, base_notes = _should_execute_stage_two(
        context=context,
        candidates=candidates,
        options=options,
        coderank_stage=coderank_stage,
    )
    if not should_run:
        if wide_handle is not None:
            _, executor = wide_handle
            executor.shutdown(wait=False)
        return WarpOutcome(hits=[], notes=base_notes, timing=None, explainability=())

    if wide_handle is not None:
        wide_future, wide_executor = wide_handle
        try:
            outcome = wide_future.result()
        except (RuntimeError, ValueError, OSError) as exc:  # pragma: no cover - defensive logging
            LOGGER.warning(
                "XTR wide search failed; falling back to narrow mode.",
                extra={"error": str(exc)},
            )
        else:
            outcome.notes.extend(base_notes)
            return outcome
        finally:
            if wide_executor is not None:
                wide_executor.shutdown(wait=False)
    return _execute_stage_two(
        context=context,
        query=query,
        candidates=candidates,
        options=options,
        base_notes=base_notes,
    )


def _run_xtr_wide_stage(
    index: XTRIndex,
    query: str,
    k: int,
    *,
    explain: bool,
    budget_ms: int | None,
) -> WarpOutcome:
    notes: list[str] = []
    with track_stage(
        "xtr_wide_search",
        budget_ms=budget_ms,
    ) as timer:
        hits = index.search(query=query, k=k, explain=explain)
    explain_payload = [(int(cid), payload) for cid, _score, payload in hits if payload]
    scored = [(int(cid), float(score)) for cid, score, _payload in hits]
    notes.append(f"XTR wide search returned {len(scored)} hits (k={k}).")
    outcome = WarpOutcome(
        hits=scored,
        notes=notes,
        timing=timer.snapshot(),
        explainability=tuple(explain_payload),
        channel="xtr",
    )
    record_stage_decision(
        COMPONENT_NAME,
        "xtr",
        decision=StageDecision(should_run=True, reason="executed"),
    )
    return outcome


def _calculate_xtr_k(limit: int, cfg: XTRConfig, options: SemanticProRuntimeOptions) -> int:
    candidate_limits = [cfg.candidate_k, limit]
    if options.xtr_k is not None and options.xtr_k > 0:
        candidate_limits.append(options.xtr_k)
    return max(candidate_limits)


def _build_extra_channels(
    warp_hits: list[tuple[int, float]],
    channel_name: str,
) -> dict[str, list[ChannelHit]] | None:
    if not warp_hits:
        return None
    return {
        channel_name: [
            ChannelHit(doc_id=str(doc_id), score=float(score)) for doc_id, score in warp_hits
        ]
    }


def _append_budget_notes(
    component: str,
    stage_timings: Sequence[StageTiming],
    limits: list[str],
) -> None:
    for timing in stage_timings:
        record_stage_metric(component, timing)
        if timing.budget_ms is None:
            continue
        if timing.exceeded_budget:
            limits.append(
                f"{timing.name} exceeded budget ({timing.duration_ms:.1f}ms > {timing.budget_ms}ms)"
            )


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        msg = f"Expected numeric chunk id, received {value!r}"
        raise VectorSearchError(msg) from exc


def _merge_rrf_weights(
    defaults: Mapping[str, float],
    overrides: Mapping[str, float],
) -> dict[str, float]:
    weights = dict(defaults or {})
    for channel, raw_value in overrides.items():
        try:
            weights[channel] = float(raw_value)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Ignoring non-numeric stage weight override",
                extra={"channel": channel, "value": raw_value},
            )
    return weights


def _run_warp_stage(
    *,
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
    options: SemanticProRuntimeOptions,
) -> tuple[list[tuple[int, float]], list[str], list[tuple[int, dict[str, Any]]], str]:
    notes: list[str] = []
    warp_hits, warp_notes = _warp_executor_hits(context, query, candidates)
    notes.extend(warp_notes)
    if warp_hits is not None:
        return warp_hits, notes, [], "warp"

    xtr_hits, xtr_notes, explain_payload = _xtr_rescore_hits(
        context=context,
        query=query,
        candidates=candidates,
        options=options,
    )
    notes.extend(xtr_notes)
    return xtr_hits, notes, explain_payload, "xtr"


def _warp_executor_hits(
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
) -> tuple[list[tuple[int, float]] | None, list[str]]:
    cfg = context.settings.warp
    notes: list[str] = []
    if not cfg.enabled:
        return None, notes
    try:
        warp_engine = WarpEngine(
            index_dir=context.paths.warp_index_dir,
            device=cfg.device,
        )
    except WarpUnavailableError as exc:
        notes.append(str(exc))
        return None, notes

    try:
        hits = warp_engine.rerank(
            query=query,
            candidate_ids=[cid for cid, _ in candidates],
            top_k=min(cfg.top_k, len(candidates)),
        )
    except WarpUnavailableError as exc:
        notes.append(str(exc))
        return None, notes

    notes.append(f"WARP executor rescored {len(hits)} candidates.")
    return hits, notes


def _xtr_rescore_hits(
    *,
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
    options: SemanticProRuntimeOptions,
) -> tuple[list[tuple[int, float]], list[str], list[tuple[int, dict[str, Any]]]]:
    notes: list[str] = []
    explain_payload: list[tuple[int, dict[str, Any]]] = []
    if not context.settings.xtr.enable:
        notes.append("XTR disabled via configuration flag.")
        return [], notes, explain_payload

    try:
        xtr_index = context.get_xtr_index()
    except RuntimeUnavailableError as exc:
        notes.append(str(exc))
        return [], notes, explain_payload
    if xtr_index is None or not xtr_index.ready:
        notes.append("XTR index unavailable; skipping late interaction.")
        return [], notes, explain_payload

    limit = options.xtr_k or context.settings.xtr.candidate_k
    candidate_ids = [cid for cid, _ in candidates][:limit]
    if not candidate_ids:
        notes.append("Insufficient candidates for XTR rescoring.")
        return [], notes, explain_payload

    rescored = xtr_index.rescore(
        query=query,
        candidate_chunk_ids=candidate_ids,
        explain=options.explain,
    )
    hits = [(chunk_id, score) for chunk_id, score, _payload in rescored]
    explain_payload = [(chunk_id, payload) for chunk_id, _score, payload in rescored if payload]
    notes.append(f"XTR rescored {len(hits)} candidates.")
    return hits, notes, explain_payload


def _hydrate_records(
    *,
    context: ApplicationContext,
    chunk_ids: list[int],
    scope: ScopeIn | None,
) -> list[dict]:
    if not chunk_ids:
        return []

    with context.open_catalog() as catalog:
        include_globs = scope.get("include_globs") if scope else None
        exclude_globs = scope.get("exclude_globs") if scope else None
        languages = scope.get("languages") if scope else None
        filters_active = bool(include_globs or exclude_globs or languages)
        if filters_active:
            return catalog.query_by_filters(
                chunk_ids,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                languages=languages,
            )
        return catalog.query_by_ids(chunk_ids)


def _hydrate_and_rerank_records(plan: HydrationPlan) -> HydrationOutcome:
    """Hydrate DuckDB records and optionally rerank them using CodeRankLLM.

    Extended Summary
    ----------------
    This function performs the hydration and reranking stage of semantic search,
    converting chunk IDs from hybrid search results into full DuckDB records with
    metadata. It optionally applies CodeRankLLM reranking when enabled in options,
    and clips results to the effective limit specified in the plan. The function
    aggregates timing information from both hydration and reranking operations,
    providing observability into stage performance. This is a critical path in the
    semantic search pipeline, bridging between vector search results and final
    ranked document outputs.

    Parameters
    ----------
    plan : HydrationPlan
        Container holding hydration and reranking inputs including context, query,
        fused hybrid search results, scope filters, effective limit, options, and
        observation tracking. The plan encapsulates all state needed to hydrate
        and rerank search results.

    Returns
    -------
    HydrationOutcome
        Dataclass containing:
        - records: list[dict], hydrated records clipped to ``effective_limit``, each
          record is a dict with chunk metadata from DuckDB.
        - timings: list[StageTiming], timing snapshots from hydration and reranking
          stages for observability.

    Raises
    ------
    VectorSearchError
        Raised when DuckDB hydration fails even after retries. This occurs when
        the database is unavailable, queries timeout, or chunk IDs are invalid.

    Notes
    -----
    Time complexity O(R + L) where R is reranking cost (if enabled, depends on
    LLM inference) and L is limit clipping. Space complexity O(k) where k is
    effective_limit. The function performs database I/O for hydration and optional
    LLM API calls for reranking. Thread-safe for concurrent plan processing.
    Results are clipped to effective_limit to respect user constraints and prevent
    memory exhaustion. Timing snapshots enable performance monitoring and debugging.
    """
    context = plan.context
    query = plan.query
    fused = plan.fused
    scope = plan.scope
    effective_limit = plan.effective_limit
    options = plan.options
    observation = plan.observation
    ordered_ids = _dedupe_preserve_order([_safe_int(doc.doc_id) for doc in fused.docs])
    timeline = current_timeline()
    requested = len(ordered_ids)
    if timeline is not None:
        timeline.event(
            "hydration.start",
            "duckdb",
            attrs={
                "requested": requested,
                "effective_limit": effective_limit,
                "asked": requested,
            },
        )
    try:
        with track_stage("duckdb_hydration") as hydration_timer:
            records = _hydrate_records(
                context=context,
                chunk_ids=ordered_ids[
                    : min(len(ordered_ids), max(effective_limit * 2, effective_limit))
                ],
                scope=scope,
            )
        snapshots = [hydration_timer.snapshot()]
    except (RuntimeError, OSError) as exc:
        if timeline is not None:
            timeline.event(
                "hydration.end",
                "duckdb",
                status="error",
                message=str(exc),
                attrs={"requested": requested, "returned": 0, "missing": requested},
            )
        observation.mark_error()
        msg = "DuckDB hydration failed"
        raise VectorSearchError(msg, cause=exc) from exc
    else:
        if timeline is not None:
            returned = len(records)
            timeline.event(
                "hydration.end",
                "duckdb",
                attrs={
                    "requested": requested,
                    "returned": returned,
                    "missing": max(requested - returned, 0),
                    "effective_limit": effective_limit,
                },
            )

    rerank_cfg = context.settings.coderank_llm
    if not options.use_reranker:
        record_stage_decision(
            COMPONENT_NAME,
            RERANK_STAGE_NAME,
            decision=StageDecision(should_run=False, reason="disabled_option"),
        )
    elif not rerank_cfg.enabled:
        record_stage_decision(
            COMPONENT_NAME,
            RERANK_STAGE_NAME,
            decision=StageDecision(should_run=False, reason="disabled_config"),
        )
    elif not records:
        record_stage_decision(
            COMPONENT_NAME,
            RERANK_STAGE_NAME,
            decision=StageDecision(should_run=False, reason="no_candidates"),
        )
    else:
        with track_stage(
            RERANK_STAGE_NAME,
            budget_ms=rerank_cfg.budget_ms,
        ) as rerank_timer:
            records = _maybe_rerank(
                query=query,
                records=records,
                context=context,
                enabled=True,
            )
        snapshots.append(rerank_timer.snapshot())
        record_stage_decision(
            COMPONENT_NAME,
            RERANK_STAGE_NAME,
            decision=StageDecision(should_run=True, reason="executed"),
        )

    return HydrationOutcome(records=records[:effective_limit], timings=snapshots)


def _maybe_rerank(
    *,
    query: str,
    records: list[dict],
    context: ApplicationContext,
    enabled: bool,
) -> list[dict]:
    cfg = context.settings.coderank_llm
    if not enabled or not cfg.enabled or not records:
        return records

    reranker = CodeRankListwiseReranker(
        model_id=cfg.model_id,
        device=cfg.device,
        max_new_tokens=cfg.max_new_tokens,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
    )

    payload = [
        (
            int(record.get("id", -1)),
            (record.get("content") or record.get("preview") or ""),
        )
        for record in records
    ]
    payload = [(cid, text) for cid, text in payload if cid >= 0]
    if not payload:
        return records

    try:
        ordered_ids = reranker.rerank(query, payload)
    except RuntimeError as exc:
        LOGGER.warning(
            "CodeRank reranker failed; continuing without rerank.",
            extra={"error": str(exc)},
        )
        return records

    by_id = {int(record["id"]): record for record in records if "id" in record}
    reordered = [by_id[cid] for cid in ordered_ids if cid in by_id]
    remaining = [record for record in records if int(record.get("id", -1)) not in ordered_ids]
    return reordered + remaining


def _build_findings(
    *,
    records: list[dict],
    docs: Sequence[HybridResultDoc],
    contribution_map: Mapping[str, list[tuple[str, int, float]]],
    explain: bool,
) -> list[Finding]:
    score_map = {_safe_int(doc.doc_id): float(doc.score) for doc in docs}
    findings: list[Finding] = []
    for record in records:
        chunk_id = int(record.get("id", -1))
        if chunk_id < 0:
            continue
        uri = str(record.get("uri", ""))
        preview = (record.get("content") or record.get("preview") or "")[:SNIPPET_PREVIEW_CHARS]
        title = Path(uri).name or uri
        finding: Finding = {
            "type": "usage",
            "title": title,
            "location": {
                "uri": uri,
                "start_line": int(record.get("start_line") or 0),
                "start_column": 0,
                "end_line": int(record.get("end_line") or 0),
                "end_column": 0,
            },
            "snippet": preview,
            "score": float(score_map.get(chunk_id, 0.0)),
            "chunk_id": chunk_id,
        }
        doc_key = str(chunk_id)
        if explain and doc_key in contribution_map:
            parts = [
                f"{channel} rank={rank}" for channel, rank, _score in contribution_map[doc_key]
            ]
            finding["why"] = f"Fusion weights: {', '.join(parts)}"
        findings.append(finding)
    return findings


def merge_explainability_into_findings(
    findings: list[Finding],
    explainability: Sequence[tuple[int, dict[str, Any]]],
) -> None:
    """Append token-level explainability snippets to existing findings.

    Extended Summary
    ----------------
    This function enriches Finding objects with token-level alignment information
    from XTR/WARP explainability data. It matches explainability entries to findings
    by chunk_id, extracts token match summaries, and appends formatted alignment
    strings to the "why" field. The function mutates findings in-place, adding
    XTR alignment details (query token index → document token index with similarity
    scores) to help users understand why specific code chunks were retrieved.
    This is called after findings are built but before the final AnswerEnvelope
    is assembled.

    Parameters
    ----------
    findings : list[Finding]
        List of Finding dictionaries to enrich. Each finding should have a "chunk_id"
        field for matching. Findings without matching explainability entries are
        left unchanged. Mutated in-place.
    explainability : Sequence[tuple[int, dict[str, Any]]]
        Explainability data as (chunk_id, payload) tuples. Each payload should
        contain a "token_matches" key with alignment information. Empty sequences
        result in no modifications.

    Notes
    -----
    Time complexity O(n * m) where n is len(findings) and m is len(explainability)
    due to lookup construction and matching. Space complexity O(m) for the lookup
    dictionary. The function mutates findings in-place and has no return value.
    Thread-safe if findings list is not modified concurrently.

    Examples
    --------
    >>> findings = [{"chunk_id": 1, "why": "Fusion weights: coderank rank=1"}]
    >>> explain = [(1, {"token_matches": [{"q_index": 0, "doc_index": 5, "similarity": 0.8}]})]
    >>> merge_explainability_into_findings(findings, explain)
    >>> "XTR alignments" in findings[0]["why"]
    True
    """
    if not explainability:
        return
    lookup = dict(explainability)
    for finding in findings:
        chunk_id = finding.get("chunk_id")
        if chunk_id is None:
            continue
        payload = lookup.get(chunk_id)
        if not payload:
            continue
        matches = payload.get("token_matches")
        if not matches:
            continue
        summary = ", ".join(
            f"q{match['q_index']}→d{match['doc_index']}={match['similarity']:.2f}"
            for match in matches
        )
        addition = f"XTR alignments: {summary}"
        previous = finding.get("why")
        finding["why"] = f"{previous}; {addition}" if previous else addition


def _build_method_explainability(
    explainability: Sequence[tuple[int, dict[str, Any]]],
    *,
    limit: int = 5,
) -> dict[str, list[dict[str, Any]]] | None:
    """Build explainability payload for MethodInfo.

    Extended Summary
    ----------------
    This helper function converts raw explainability tuples (chunk_id, payload) into
    a structured dictionary format suitable for inclusion in MethodInfo. It filters
    entries to include only those with token matches, limits the number of entries
    to prevent payload bloat, and organizes them by channel (currently "warp").
    The function is called after the retrieval pipeline completes to package
    token-level alignment data for observability.

    Parameters
    ----------
    explainability : Sequence[tuple[int, dict[str, Any]]]
        Raw explainability data as (chunk_id, payload) tuples. Each payload should
        contain a "token_matches" key with alignment information. Empty sequences
        result in None return.
    limit : int, optional
        Maximum number of explainability entries to include in the result. Defaults
        to 5 to keep payload sizes manageable. Higher values provide more detail but
        increase response size.

    Returns
    -------
    dict[str, list[dict[str, Any]]] | None
        Structured explainability data keyed by channel name (e.g., "warp"). Each
        entry contains chunk_id and token_matches. Returns None if no valid entries
        are found or if explainability is empty.

    Notes
    -----
    Time complexity O(n) where n is min(len(explainability), limit). Space complexity
    O(n) for the result dictionary. No I/O or side effects. Thread-safe.

    Examples
    --------
    >>> explain = [(1, {"token_matches": [{"q_index": 0, "doc_index": 5, "similarity": 0.8}]})]
    >>> result = _build_method_explainability(explain, limit=5)
    >>> result is not None and "warp" in result
    True
    >>> result = _build_method_explainability([], limit=5)
    >>> result is None
    True
    """
    if not explainability:
        return None
    entries: list[dict[str, Any]] = []
    for chunk_id, payload in explainability[:limit]:
        token_matches = list(payload.get("token_matches", []))
        if not token_matches:
            continue
        entries.append(
            {
                "chunk_id": chunk_id,
                "token_matches": token_matches,
            }
        )
    if not entries:
        return None
    return {"warp": entries}


def _build_method(context: MethodContext) -> MethodInfo:
    elapsed_ms = int((perf_counter() - context.start_time) * 1000)
    coverage = f"{context.findings_count}/{context.effective_limit} results in {elapsed_ms}ms"
    if context.requested_limit != context.effective_limit:
        coverage = f"{coverage} (requested {context.requested_limit})"
    base: MethodInfo = {
        "retrieval": list(dict.fromkeys(context.channels)),
        "coverage": coverage,
    }
    if context.hybrid_method:
        method = cast("MethodInfo", dict(context.hybrid_method))
        coverage = base.get("coverage")
        retrieval = base.get("retrieval")
        if coverage is not None and "coverage" not in method:
            method["coverage"] = coverage
        if retrieval is not None and "retrieval" not in method:
            method["retrieval"] = retrieval
    else:
        method = base
    if context.stages:
        method["stages"] = [cast("StageInfo", stage.as_payload()) for stage in context.stages]
    if context.notes:
        existing_notes = (
            list(method.get("notes", [])) if isinstance(method.get("notes"), list) else []
        )
        method["notes"] = list(dict.fromkeys([*existing_notes, *context.notes]))
    if context.explainability:
        merged_exp = (
            dict(method.get("explainability", {}))
            if isinstance(method.get("explainability"), dict)
            else {}
        )
        merged_exp.update(context.explainability)
        method["explainability"] = merged_exp
    if context.rerank:
        method["rerank"] = context.rerank
    return method


def _assemble_extras(
    *,
    method: MethodInfo,
    limits: list[str],
    scope: ScopeIn | None,
) -> AnswerEnvelope:
    """Assemble response metadata extras dictionary.

    Extended Summary
    ----------------
    This helper function constructs the extras dictionary for an AnswerEnvelope,
    combining method metadata (retrieval channels, coverage, stage timings) with
    optional limits warnings and scope filters. It is called after the retrieval
    pipeline completes to package telemetry and configuration context into the
    response. The function ensures that only non-empty optional fields are included,
    keeping the response payload minimal.

    Parameters
    ----------
    method : MethodInfo
        Method metadata dictionary containing retrieval channels, coverage string,
        and optional stage timings. This is produced by _build_method() and describes
        how the search was executed.
    limits : list[str]
        List of warning messages about budget overruns, limit clamping, or other
        operational constraints. Empty list means no warnings. Non-empty lists are
        included in the extras as the "limits" field.
    scope : ScopeIn | None
        Scope filters that were applied during search (include_globs, exclude_globs,
        languages). None means no scope filtering was applied. Non-None values are
        included in the extras as the "scope" field.

    Returns
    -------
    AnswerEnvelope
        Dictionary containing the method field (always present) and optionally
        limits and scope fields if they are non-empty/non-None. This dictionary
        is merged into the final AnswerEnvelope by _make_envelope().

    Notes
    -----
    Time complexity O(1). No I/O or side effects. The function performs shallow
    dictionary construction only. Thread-safe.

    Examples
    --------
    >>> method = {"retrieval": ["coderank"], "coverage": "5/10 results in 42ms"}
    >>> extras = _assemble_extras(method=method, limits=[], scope=None)
    >>> extras["method"] == method
    True
    >>> "limits" in extras
    False
    >>> extras = _assemble_extras(method=method, limits=["Budget exceeded"], scope=None)
    >>> extras["limits"] == ["Budget exceeded"]
    True
    """
    extras: AnswerEnvelope = {"method": method}
    if limits:
        extras["limits"] = limits
    if scope:
        extras["scope"] = scope
    return extras


def _make_envelope(
    *,
    answer: str,
    findings: list[Finding],
    extras: AnswerEnvelope,
) -> AnswerEnvelope:
    envelope: AnswerEnvelope = {
        "answer": answer,
        "query_kind": "semantic_pro",
        "findings": findings,
        "confidence": 0.9 if findings else 0.0,
    }
    envelope.update(extras)
    return envelope


def _clamp_limit(requested: int, max_results: int, notes: list[str]) -> int:
    if requested <= 0:
        notes.append("Requested limit <= 0; defaulting to 1.")
    if requested > max_results:
        notes.append(f"Requested limit {requested} exceeds max_results {max_results}; truncating.")
    effective = requested
    if effective <= 0:
        effective = 1
    return min(effective, max_results)


def _coerce_positive_int(value: object) -> int | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dedupe_preserve_order(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for chunk_id in ids:
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        ordered.append(chunk_id)
    return ordered


@dataclass(slots=True, frozen=True)
class WarpOutcome:
    """Container describing the results of the optional WARP stage."""

    hits: list[tuple[int, float]]
    notes: list[str]
    timing: StageTiming | None
    explainability: tuple[tuple[int, dict[str, Any]], ...]
    channel: str = "warp"


@dataclass(slots=True, frozen=True)
class FusionRequest:
    """Inputs required to execute the fusion stage."""

    query: str
    coderank_hits: Sequence[tuple[int, float]]
    warp_hits: list[tuple[int, float]]
    warp_channel: str
    effective_limit: int
    weights: Mapping[str, float]
    faiss_k: int
    nprobe: int


@dataclass(slots=True, frozen=True)
class MethodContext:
    """Inputs required to build the MethodInfo payload."""

    findings_count: int
    requested_limit: int
    effective_limit: int
    start_time: float
    channels: list[str]
    stages: Sequence[StageTiming] | None
    notes: tuple[str, ...] | None = None
    explainability: dict[str, list[dict[str, Any]]] | None = None
    rerank: dict[str, object] | None = None
    hybrid_method: MethodInfo | None = None
