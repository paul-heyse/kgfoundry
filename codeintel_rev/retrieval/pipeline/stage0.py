"""Stage-0 hybrid retrieval helpers shared across MCP adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import SearchRuntimeOverrides
from codeintel_rev.io.hybrid_search import (
    HybridSearchEngine,
    HybridSearchOptions,
    HybridSearchTuning,
)
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.mcp_server.method_metadata import normalize_stage0_method
from codeintel_rev.mcp_server.schemas import ScopeIn, Stage0MethodInfo
from codeintel_rev.retrieval.types import SearchHit
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.errors import EmbeddingError

if TYPE_CHECKING:
    import httpx
    import numpy as np

    from codeintel_rev.app.config_context import ApplicationContext
else:
    httpx = cast("Any", LazyModule("httpx", "stage0 semantic embeddings HTTP handling"))
    np = cast("Any", LazyModule("numpy", "stage0 semantic embeddings array math"))


@dataclass(slots=True, frozen=True)
class Stage0ChannelHit:
    """Minimal hit representation for injecting extra channels."""

    doc_id: str
    rank: int
    score: float

    @classmethod
    def from_tuple(cls, payload: tuple[str | int, int, float]) -> Stage0ChannelHit:
        """Return a normalized hit from tuple payloads.

        Returns
        -------
        Stage0ChannelHit
            Dataclass instance mirroring :class:`SearchHit` fields.
        """
        doc_id, rank, score = payload
        return cls(doc_id=str(doc_id), rank=int(rank), score=float(score))


type Stage0ChannelHitInput = Stage0ChannelHit | tuple[str | int, int, float]


def _normalize_extra_channels(
    extra_channels: Mapping[str, Sequence[Stage0ChannelHitInput]] | None,
) -> Mapping[str, list[SearchHit]] | None:
    """Return extra channels normalized to :class:`SearchHit` sequences.

    Returns
    -------
    Mapping[str, list[SearchHit]] | None
        Mapping keyed by channel name, or ``None`` when no extra channels
        were provided.
    """
    if not extra_channels:
        return None

    normalized: dict[str, list[SearchHit]] = {}
    for channel, hits in extra_channels.items():
        normalized_hits: list[SearchHit] = []
        for hit in hits:
            candidate = (
                hit if isinstance(hit, Stage0ChannelHit) else Stage0ChannelHit.from_tuple(hit)
            )
            normalized_hits.append(
                SearchHit(
                    doc_id=candidate.doc_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    source=channel,
                )
            )
        normalized[channel] = normalized_hits
    return normalized


@dataclass(slots=True, frozen=True)
class Stage0Options:
    """Optional knobs passed to the hybrid search engine."""

    weights: Mapping[str, float] | None = None
    extra_channels: Mapping[str, Sequence[Stage0ChannelHitInput]] | None = None
    tuning: HybridSearchTuning | None = None
    faiss_ready: bool = True


@dataclass(slots=True, frozen=True)
class Stage0Result:
    """Normalized Stage-0 fusion outputs."""

    ids: list[int]
    scores: list[float]
    warnings: list[str]
    method: Stage0MethodInfo | None
    channels: list[str]
    contributions: Mapping[int, list[tuple[str, int, float]]] | None


@dataclass(slots=True, frozen=True)
class Stage0Metadata:
    """Additional metadata surfaced alongside the Stage-0 result."""

    limits: tuple[str, ...]
    effective_limit: int
    requested_limit: int


@dataclass(slots=True, frozen=True)
class SemanticStage0Request:
    """Inputs required to execute the semantic FAISS → hybrid pipeline."""

    context: ApplicationContext
    query: str
    limit: int
    scope: ScopeIn | None
    options: Stage0Options | None = None


@dataclass(slots=True, frozen=True)
class _ScopeFilterFlags:
    has_include_globs: bool
    has_exclude_globs: bool
    has_languages: bool

    @classmethod
    def from_scope(cls, scope: ScopeIn | None) -> _ScopeFilterFlags:
        """Extract filter flags from a scope configuration.

        Parameters
        ----------
        scope : ScopeIn | None
            Scope configuration dictionary, or None if no scope is provided.

        Returns
        -------
        _ScopeFilterFlags
            Flags indicating which filter types are present in the scope.
        """
        return cls(
            has_include_globs=bool(scope and scope.get("include_globs")),
            has_exclude_globs=bool(scope and scope.get("exclude_globs")),
            has_languages=bool(scope and scope.get("languages")),
        )

    @property
    def has_filters(self) -> bool:
        """Return True if any filter flags are set.

        Returns
        -------
        bool
            True if include_globs, exclude_globs, or languages filters are present.
        """
        return self.has_include_globs or self.has_exclude_globs or self.has_languages


@dataclass(slots=True, frozen=True)
class _FaissFanout:
    faiss_k: int
    faiss_k_target: int


@dataclass(slots=True, frozen=True)
class _SearchBudget:
    effective_limit: int
    max_results: int
    limits_metadata: tuple[str, ...]
    faiss_ready: bool


@dataclass(slots=True, frozen=True)
class _SemanticSearchPlan:
    scope_flags: _ScopeFilterFlags
    tuning_overrides: Mapping[str, float | int]
    limits_metadata: tuple[str, ...]
    effective_limit: int
    fanout: _FaissFanout
    nprobe: int
    faiss_ready: bool


@dataclass(slots=True, frozen=True)
class _FaissStageResult:
    ids: list[int]
    scores: list[float]
    exception: Exception | None


@dataclass(slots=True, frozen=True)
class _HybridResult:
    ids: list[int]
    scores: list[float]
    warnings: list[str]
    method: Stage0MethodInfo | None
    channels: list[str]
    contributions: Mapping[int, list[tuple[str, int, float]]] | None


@dataclass(slots=True, frozen=True)
class _HybridResolveParams:
    context: ApplicationContext
    query: str
    plan: _SemanticSearchPlan
    limits_metadata: list[str]
    options: Stage0Options | None


@dataclass(slots=True, frozen=True)
class _FaissSearchConfig:
    context: ApplicationContext
    catalog: DuckDBCatalog
    limit: int
    nprobe: int
    overrides: Mapping[str, float | int] | None


def run_stage0(
    engine: HybridSearchEngine,
    *,
    query: str,
    semantic_hits: Sequence[tuple[int, float]],
    limit: int,
    options: Stage0Options | None = None,
) -> Stage0Result:
    """Execute the hybrid search engine and normalize outputs.

    Parameters
    ----------
    engine : HybridSearchEngine
        Hybrid search engine instance for fusing semantic and sparse channels.
    query : str
        Query text for hybrid search.
    semantic_hits : Sequence[tuple[int, float]]
        Pre-computed semantic hits as (chunk_id, score) pairs.
    limit : int
        Maximum number of results to return.
    options : Stage0Options | None, optional
        Optional search options for tuning weights, channels, and FAISS readiness.

    Returns
    -------
    Stage0Result
        Normalized IDs, scores, channels, contributions, and method metadata.
    """
    opts = options or Stage0Options()
    hs_options = HybridSearchOptions(
        extra_channels=_normalize_extra_channels(opts.extra_channels),
        weights=opts.weights,
        tuning=opts.tuning,
        faiss_ready=opts.faiss_ready,
    )
    hybrid_result = engine.search(
        query=query,
        semantic_hits=list(semantic_hits),
        limit=limit,
        options=hs_options,
    )
    return Stage0Result(
        ids=[int(doc.doc_id) for doc in hybrid_result.docs],
        scores=[float(doc.score) for doc in hybrid_result.docs],
        warnings=list(hybrid_result.warnings or []),
        method=normalize_stage0_method(hybrid_result.method),
        channels=list(hybrid_result.channels or []),
        contributions={
            int(chunk_id): value for chunk_id, value in hybrid_result.contributions.items()
        }
        if hybrid_result.contributions
        else None,
    )


def execute_semantic_stage0(request: SemanticStage0Request) -> tuple[Stage0Result, Stage0Metadata]:
    """Embed query text, run FAISS, and fuse channels via the hybrid engine.

    Parameters
    ----------
    request : SemanticStage0Request
        Stage-0 request containing context, query, limit, scope, and options.

    Returns
    -------
    tuple[Stage0Result, Stage0Metadata]
        Stage-0 retrieval outputs alongside effective limits and limit metadata.
    """
    plan = _build_semantic_search_plan(request.context, request.scope, request.limit)
    limits_metadata = list(plan.limits_metadata)
    query_vector: NDArrayF32 | None = None

    if plan.faiss_ready:
        query_vector = _embed_query_or_raise(
            request.context.vllm_client,
            request.query,
            request.context.settings.vllm.base_url,
        )

    with request.context.open_catalog() as catalog:
        faiss_stage = _run_faiss_stage(request, plan, catalog, query_vector, limits_metadata)
        hybrid = _resolve_hybrid_results(
            faiss_stage,
            _HybridResolveParams(
                context=request.context,
                query=request.query,
                plan=plan,
                limits_metadata=limits_metadata,
                options=request.options,
            ),
        )

    final_limits = tuple(limits_metadata)
    metadata = Stage0Metadata(
        limits=final_limits,
        effective_limit=plan.effective_limit,
        requested_limit=request.limit,
    )
    return (
        Stage0Result(
            ids=hybrid.ids,
            scores=hybrid.scores,
            warnings=hybrid.warnings,
            method=hybrid.method,
            channels=hybrid.channels,
            contributions=hybrid.contributions,
        ),
        metadata,
    )


def _run_faiss_stage(
    request: SemanticStage0Request,
    plan: _SemanticSearchPlan,
    catalog: DuckDBCatalog,
    query_vector: NDArrayF32 | None,
    limits_metadata: list[str],
) -> _FaissStageResult:
    """Execute the FAISS lookup stage for semantic search.

    Extended Summary
    ----------------
    Runs the FAISS ANN search when embeddings are available and annotates
    ``limits_metadata`` with fallback reasons when the search cannot run or
    is suppressed due to low semantic scores.

    Parameters
    ----------
    request : SemanticStage0Request
        Stage-0 request containing context and query information.
    plan : _SemanticSearchPlan
        Search plan with tuning overrides and fan-out configuration.
    catalog : DuckDBCatalog
        DuckDB catalog for chunk retrieval.
    query_vector : NDArrayF32 | None
        Query embedding vector. If None, FAISS stage is skipped.
    limits_metadata : list[str]
        Mutable list for appending limit and fallback metadata.

    Returns
    -------
    _FaissStageResult
        Result containing IDs, scores, and optional exception.
    """
    if not (plan.faiss_ready and query_vector is not None):
        return _FaissStageResult([], [], None)

    search_config = _FaissSearchConfig(
        context=request.context,
        catalog=catalog,
        limit=plan.fanout.faiss_k,
        nprobe=plan.nprobe,
        overrides=plan.tuning_overrides,
    )
    result_ids, result_scores, search_exc = _run_faiss_search(
        config=search_config,
        query_vector=query_vector,
    )
    if search_exc is not None:
        limits_metadata.append("faiss_fallback:unavailable")
        return _FaissStageResult([], [], search_exc)

    threshold = float(request.context.settings.index.semantic_min_score or 0.0)
    if threshold > 0.0 and result_scores and float(result_scores[0]) < threshold:
        limits_metadata.append("faiss_fallback:low_score")
        return _FaissStageResult([], [], None)

    return _FaissStageResult(list(result_ids), list(result_scores), None)


def _resolve_hybrid_results(
    faiss_stage: _FaissStageResult,
    params: _HybridResolveParams,
) -> _HybridResult:
    """Fuse FAISS outputs with hybrid search engine results.

    Extended Summary
    ----------------
    Hydrates FAISS hits, executes the HybridSearchEngine, records warnings,
    and normalizes contribution maps to integer chunk IDs.

    Parameters
    ----------
    faiss_stage : _FaissStageResult
        FAISS stage results containing IDs and scores.
    params : _HybridResolveParams
        Parameters for hybrid search resolution.

    Returns
    -------
    _HybridResult
        Fused result with IDs, scores, warnings, method metadata, channels,
        and contribution map.
    """
    hydration_ids = list(faiss_stage.ids)
    hydration_scores = list(faiss_stage.scores)
    channels_out: list[str] = ["semantic", "faiss"]

    try:
        hybrid_engine = params.context.get_hybrid_engine()
    except RuntimeError as exc:
        params.limits_metadata.append(f"Hybrid search unavailable: {exc}")
        return _HybridResult(
            ids=hydration_ids,
            scores=hydration_scores,
            warnings=list(params.limits_metadata),
            method=None,
            channels=channels_out,
            contributions=None,
        )

    opts = params.options or Stage0Options()
    tuning = opts.tuning or HybridSearchTuning(
        k=params.plan.fanout.faiss_k, nprobe=params.plan.nprobe
    )
    normalized_channels = _normalize_extra_channels(opts.extra_channels)
    faiss_ready_flag = opts.faiss_ready if params.options is not None else params.plan.faiss_ready
    hybrid_result = hybrid_engine.search(
        query=params.query,
        semantic_hits=list(zip(faiss_stage.ids, faiss_stage.scores, strict=False)),
        limit=params.plan.effective_limit,
        options=HybridSearchOptions(
            extra_channels=normalized_channels,
            weights=opts.weights,
            tuning=tuning,
            faiss_ready=faiss_ready_flag,
        ),
    )
    if hybrid_result.warnings:
        params.limits_metadata.extend(hybrid_result.warnings)

    fused_ids: list[int] = []
    fused_scores: list[float] = []
    fused_contributions: dict[int, list[tuple[str, int, float]]] = {}
    for doc in hybrid_result.docs:
        try:
            chunk_id_int = int(doc.doc_id)
        except ValueError:
            params.limits_metadata.append(
                f"Hybrid result skipped (non-numeric chunk id): {doc.doc_id}"
            )
            continue

        fused_ids.append(chunk_id_int)
        fused_scores.append(float(doc.score))
        if hybrid_result.contributions:
            fused_contributions[chunk_id_int] = hybrid_result.contributions.get(doc.doc_id, [])

    if fused_ids:
        channels_out = list(dict.fromkeys(["semantic", "faiss", *hybrid_result.channels]))
        contributions: Mapping[int, list[tuple[str, int, float]]] | None = (
            fused_contributions or None
        )
        return _HybridResult(
            ids=fused_ids[: params.plan.effective_limit],
            scores=fused_scores[: params.plan.effective_limit],
            warnings=list(params.limits_metadata),
            method=normalize_stage0_method(hybrid_result.method),
            channels=channels_out,
            contributions=contributions,
        )

    return _HybridResult(
        ids=hydration_ids[: params.plan.effective_limit],
        scores=hydration_scores[: params.plan.effective_limit],
        warnings=list(params.limits_metadata),
        method=normalize_stage0_method(hybrid_result.method),
        channels=channels_out,
        contributions=None,
    )


def _build_semantic_search_plan(
    context: ApplicationContext,
    scope: ScopeIn | None,
    requested_limit: int,
) -> _SemanticSearchPlan:
    """Derive tuning overrides, fan-out, and limits for Stage-0 retrieval.

    Extended Summary
    ----------------
    Normalizes scope-provided FAISS tuning overrides, clamps requested limits
    to the configured maxima, and describes fan-out/nprobe decisions needed
    for the semantic stage.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and configuration.
    scope : ScopeIn | None
        Optional scope filters for limiting search results.
    requested_limit : int
        Requested number of results to return.

    Returns
    -------
    _SemanticSearchPlan
        Search plan with scope flags, tuning overrides, limits metadata,
        effective limit, fan-out configuration, nprobe, and FAISS readiness.
    """
    scope_flags = _ScopeFilterFlags.from_scope(scope)
    tuning_overrides, tuning_warnings = _normalize_scope_faiss_tuning(
        scope.get("faiss_tuning") if scope else None
    )
    budget = _build_search_budget(context, requested_limit)
    multiplier = max(1, context.settings.limits.semantic_overfetch_multiplier)
    fanout = _calculate_faiss_fanout(
        budget.effective_limit,
        budget.max_results,
        multiplier,
        scope_flags,
    )

    limits_metadata = [*budget.limits_metadata]
    if fanout.faiss_k < fanout.faiss_k_target:
        limits_metadata.append(
            f"FAISS fan-out clamped to {fanout.faiss_k} (max_results={budget.max_results})."
        )
    limits_metadata.extend(tuning_warnings)

    faiss_nprobe = int(tuning_overrides.get("nprobe", context.settings.index.faiss_nprobe))
    return _SemanticSearchPlan(
        scope_flags=scope_flags,
        tuning_overrides=tuning_overrides,
        limits_metadata=tuple(limits_metadata),
        effective_limit=budget.effective_limit,
        fanout=fanout,
        nprobe=faiss_nprobe,
        faiss_ready=budget.faiss_ready,
    )


def _build_search_budget(
    context: ApplicationContext,
    requested_limit: int,
) -> _SearchBudget:
    """Clamp the requested limit and determine whether FAISS is ready.

    Extended Summary
    ----------------
    Applies max-result clamps, consults ``ensure_faiss_ready()``, and captures
    metadata describing clamp reasons and FAISS readiness.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and FAISS state.
    requested_limit : int
        Requested number of results to return.

    Returns
    -------
    _SearchBudget
        Budget containing effective limit, max results, limits metadata,
        and FAISS readiness status.
    """
    max_results = max(1, context.settings.limits.max_results)
    effective_limit, clamp_messages = _clamp_result_limit(requested_limit, max_results)

    ready, faiss_limits, faiss_error = context.ensure_faiss_ready()
    limits_metadata: tuple[str, ...] = tuple(faiss_limits) + tuple(clamp_messages)
    if not ready:
        note = faiss_error or "Semantic search not available - index not built"
        limits_metadata = (*limits_metadata, f"faiss_fallback:unavailable ({note})")
    return _SearchBudget(
        effective_limit=effective_limit,
        max_results=max_results,
        limits_metadata=limits_metadata,
        faiss_ready=ready,
    )


def _clamp_result_limit(requested_limit: int, max_results: int) -> tuple[int, list[str]]:
    messages: list[str] = []
    if requested_limit <= 0:
        messages.append(f"Requested limit {requested_limit} is not positive; using minimum of 1.")
    if requested_limit > max_results:
        messages.append(
            f"Requested limit {requested_limit} exceeds max_results {max_results}; "
            f"truncating to {max_results}."
        )

    effective_limit = max(1, min(requested_limit, max_results))
    return effective_limit, messages


def _calculate_faiss_fanout(
    effective_limit: int,
    max_results: int,
    multiplier: int,
    scope_flags: _ScopeFilterFlags,
) -> _FaissFanout:
    faiss_k_target = effective_limit
    if scope_flags.has_filters:
        faiss_k_target = effective_limit * multiplier
        faiss_k_target += _overfetch_bonus(effective_limit, scope_flags)

    faiss_k = max(
        effective_limit,
        min(max_results, faiss_k_target),
    )
    return _FaissFanout(faiss_k, faiss_k_target)


def _overfetch_bonus(effective_limit: int, scope_flags: _ScopeFilterFlags) -> int:
    if scope_flags.has_include_globs and scope_flags.has_languages:
        return effective_limit
    if scope_flags.has_include_globs or scope_flags.has_languages:
        return max(1, effective_limit // 2)
    return 0


def _run_faiss_search(
    *,
    config: _FaissSearchConfig,
    query_vector: NDArrayF32,
) -> tuple[list[int], list[float], Exception | None]:
    """Execute a FAISS search with runtime overrides applied.

    Extended Summary
    ----------------
    Applies dynamic runtime overrides (nprobe/efSearch/k_factor) and proxies
    the request to the shared ``FAISSManager`` instance.

    Parameters
    ----------
    config : _FaissSearchConfig
        Search configuration containing context, catalog, limits, and overrides.
    query_vector : NDArrayF32
        Normalized query embedding with shape ``(1, dim)``.

    Returns
    -------
    tuple[list[int], list[float], Exception | None]
        Tuple of result IDs, scores, and optional exception when FAISS search fails.
    """
    try:
        overrides = dict(config.overrides or {})
        final_nprobe = int(overrides.get("nprobe", config.nprobe))
        runtime = SearchRuntimeOverrides(
            ef_search=int(overrides["ef_search"]) if "ef_search" in overrides else None,
            quantizer_ef_search=(
                int(overrides["quantizer_ef_search"])
                if "quantizer_ef_search" in overrides
                else None
            ),
            k_factor=float(overrides["k_factor"]) if "k_factor" in overrides else None,
        )
        distances, ids = config.context.faiss_manager.search(
            query_vector,
            k=config.limit,
            nprobe=final_nprobe,
            runtime=runtime,
            catalog=config.catalog,
        )
    except RuntimeError as exc:
        return [], [], exc

    return ids[0].tolist(), distances[0].tolist(), None


def _normalize_scope_faiss_tuning(
    raw: Mapping[str, object] | None,
) -> tuple[dict[str, float | int], list[str]]:
    if not raw:
        return {}, []

    alias_map = {
        "nprobe": "nprobe",
        "ef_search": "ef_search",
        "efSearch": "ef_search",
        "quantizer_ef_search": "quantizer_ef_search",
        "quantizer_efSearch": "quantizer_ef_search",
        "k_factor": "k_factor",
        "kFactor": "k_factor",
    }
    overrides: dict[str, float | int] = {}
    warnings: list[str] = []

    for key, value in raw.items():
        normalized = alias_map.get(key)
        if normalized is None:
            warnings.append(f"Ignored unsupported faiss_tuning.{key} override.")
            continue
        caster = float if normalized == "k_factor" else int
        if not isinstance(value, (int, float, str)):
            warnings.append(f"Ignored invalid faiss_tuning.{key} override.")
            continue
        try:
            coerced = caster(value)
        except (TypeError, ValueError):
            warnings.append(f"Ignored invalid faiss_tuning.{key} override.")
            continue
        overrides[normalized] = coerced
    return overrides, warnings


def _embed_query_or_raise(
    client: VLLMClient,
    query: str,
    vllm_url: str,
) -> NDArrayF32:
    embedding, embed_error = _embed_query(client, query)
    if embedding is None or embed_error is not None:
        raise EmbeddingError(
            embed_error or "Embedding service unavailable",
            context={"vllm_url": vllm_url},
        )

    return embedding


def _embed_query(client: VLLMClient, query: str) -> tuple[NDArrayF32 | None, str | None]:
    try:
        vector = client.embed_single(query)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        return None, f"Embedding service unavailable: {exc}"

    array = np.array(vector, dtype=np.float32).reshape(1, -1)
    return array, None


__all__ = [
    "SemanticStage0Request",
    "Stage0ChannelHit",
    "Stage0Metadata",
    "Stage0Options",
    "Stage0Result",
    "execute_semantic_stage0",
    "run_stage0",
]
