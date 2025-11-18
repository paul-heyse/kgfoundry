"""Two-stage semantic search adapter built on the retrieval pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations, relation_exists
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.mcp_server.adapters.async_dependencies import (
    AsyncSearchDependencies,
    build_async_dependencies,
)
from codeintel_rev.mcp_server.method_metadata import MethodInfoComponents
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    ExplanationPayload,
    Finding,
    MethodGatingInfo,
    MethodInfo,
    MethodRerankerInfo,
    ScopeIn,
)
from codeintel_rev.retrieval.pipeline import (
    Doc,
    StageDecision,
    StageGateConfig,
    XTRLateInteraction,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import CodeRankLLMAdapter, RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Metadata,
    Stage0Options,
    Stage0Result,
    execute_semantic_stage0,
)
from kgfoundry_common.errors import VectorSearchError

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


RelationChecker = Callable[["DuckDBPyConnection", str], bool]

try:
    from codeintel_rev.io.rerank_coderankllm import (
        CodeRankGenerationSettings,
        CodeRankListwiseReranker,
        CoderankLLMRerankerContext,
    )
except ImportError:  # pragma: no cover - optional dependency
    CodeRankGenerationSettings = None
    CodeRankListwiseReranker = None
    CoderankLLMRerankerContext = None

SNIPPET_PREVIEW_CHARS = 500


class _CoderankLLMConfig(Protocol):
    """Protocol for CodeRank LLM configuration object."""

    model_id: str
    device: str
    max_new_tokens: int
    temperature: float
    top_p: float


class _RerankAdapter(Protocol):
    """Protocol describing the reranker adapter surface."""

    def rerank(self, query: str, docs: Sequence[Doc]) -> RerankResult:
        """Return reranked IDs and scores for the provided documents."""
        ...


RerankAdapter = _RerankAdapter


class RerankOptionPayload(TypedDict, total=False):
    """User-facing payload for overruling rerank behavior."""

    enabled: bool
    top_k: int | None
    provider: str | None


class SemanticProOptions(TypedDict, total=False):
    """User-facing options for semantic_pro retrieval."""

    use_coderank: bool
    use_warp: bool
    use_reranker: bool
    stage_weights: Mapping[str, float]
    explain: bool
    xtr_k: int
    rerank: RerankOptionPayload


@dataclass(frozen=True)
class RerankRuntimeOptions:
    """Runtime overrides for optional LLM reranking."""

    enabled: bool = False
    top_k: int | None = None
    provider: str | None = None


@dataclass(frozen=True)
class SemanticProRuntimeOptions:
    """Normalizer for user-provided semantic_pro options."""

    use_coderank: bool = True
    use_warp: bool = True
    use_reranker: bool = False
    stage_weights: Mapping[str, float] = field(default_factory=dict)
    explain: bool = False
    xtr_k: int | None = None
    rerank: RerankRuntimeOptions | None = None


@dataclass(slots=True, frozen=True)
class SemanticProHooks:
    """Injection points for orchestrating the semantic_pro pipeline."""

    execute_stage0: Callable[[SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]]
    decide_stage_two: Callable[[ApplicationContext, Sequence[int], Sequence[float]], StageDecision]
    run_late_interaction: Callable[
        [ApplicationContext, str, Sequence[int], SemanticProRuntimeOptions],
        LateInteractionResult | None,
    ]
    apply_reranker: Callable[
        [_RerankerRequest, RerankerDependencies | None],
        tuple[list[int], list[float], MethodRerankerInfo],
    ]
    hydrate_findings: Callable[
        [ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None],
        list[Finding],
    ]


@dataclass(slots=True)
class _StageState:
    """Mutable container tracking Stage-0 candidate state."""

    ids: list[int]
    scores: list[float]
    limits: list[str]
    stage1_channel: str | None = None
    explanations: list[tuple[int, dict[str, Any]]] | None = None
    rerank_metadata: MethodRerankerInfo | None = None


@dataclass(slots=True, frozen=True)
class _SyncSearchRequest:
    """Immutable payload passed to the synchronous search helper."""

    context: ApplicationContext
    query: str
    limit: int
    scope: ScopeIn | None
    options: SemanticProRuntimeOptions


@dataclass(slots=True, frozen=True)
class _RerankerRequest:
    """Inputs required to execute the optional reranker."""

    context: ApplicationContext
    query: str
    ids: list[int]
    scores: list[float]
    options: SemanticProRuntimeOptions


@dataclass(slots=True, frozen=True)
class RerankerDependencies:
    """Injection points for reranker orchestration."""

    adapter_builder: Callable[[_CoderankLLMConfig], RerankAdapter | None]
    doc_fetcher: Callable[
        [ApplicationContext, Sequence[int], RelationChecker],
        list[dict],
    ]
    relation_checker: RelationChecker


def build_runtime_options(options: SemanticProOptions | None) -> SemanticProRuntimeOptions:
    """Normalize incoming options into a frozen runtime dataclass.

    Parameters
    ----------
    options : SemanticProOptions | None
        Optional options dictionary from request payload.

    Returns
    -------
    SemanticProRuntimeOptions
        Normalized runtime options with parsed values and defaults applied.
    """
    if options is None:
        return SemanticProRuntimeOptions()

    xtr_k_value = options.get("xtr_k")
    try:
        parsed_xtr_k = int(xtr_k_value) if xtr_k_value is not None else None
    except (TypeError, ValueError):
        parsed_xtr_k = None

    rerank_payload = options.get("rerank")
    rerank_runtime = None
    if isinstance(rerank_payload, Mapping):
        top_k = rerank_payload.get("top_k")
        try:
            parsed_top = int(top_k) if top_k is not None else None
        except (TypeError, ValueError):
            parsed_top = None
        rerank_runtime = RerankRuntimeOptions(
            enabled=bool(rerank_payload.get("enabled", True)),
            top_k=parsed_top,
            provider=rerank_payload.get("provider"),
        )

    return SemanticProRuntimeOptions(
        use_coderank=options.get("use_coderank", True),
        use_warp=options.get("use_warp", True),
        use_reranker=options.get("use_reranker", False),
        stage_weights=dict(options.get("stage_weights", {})),
        explain=options.get("explain", False),
        xtr_k=parsed_xtr_k,
        rerank=rerank_runtime,
    )


async def semantic_search_pro(
    context: ApplicationContext,
    *,
    query: str,
    limit: int,
    options: SemanticProOptions | None = None,
    async_deps: AsyncSearchDependencies | None = None,
) -> AnswerEnvelope:
    """Execute semantic search with Pro pipeline orchestration.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and managers.
    query : str
        Search query text.
    limit : int
        Maximum number of results to return. Must be positive.
    options : SemanticProOptions | None, optional
        Optional search options for tuning behavior.
    async_deps : AsyncSearchDependencies | None, optional
        Dependency bundle controlling session resolution, scope lookup, and
        threadpool execution for the sync helper.

    Returns
    -------
    AnswerEnvelope
        Search results envelope with chunks, metadata, and method information.

    Raises
    ------
    VectorSearchError
        When limit is not positive.
    """
    if limit <= 0:
        message = f"limit must be positive, got {limit}"
        raise VectorSearchError(message)

    runtime_options = build_runtime_options(options)
    deps = async_deps or _DEFAULT_ASYNC_DEPS
    session = deps.session_provider()
    scope: ScopeIn | None
    scope = None
    if scope is None:
        scope = await deps.scope_resolver(context, session)

    return await deps.to_thread(
        _semantic_search_pro_sync,
        _SyncSearchRequest(
            context=context,
            query=query,
            limit=limit,
            scope=scope,
            options=runtime_options,
        ),
    )


def _semantic_search_pro_sync(
    request: _SyncSearchRequest,
    *,
    hooks: SemanticProHooks | None = None,
) -> AnswerEnvelope:
    """Execute synchronous semantic search orchestration.

    Parameters
    ----------
    request : _SyncSearchRequest
        Search request object containing context, query, limit, scope, and options.
        The request encapsulates all inputs needed for semantic search execution.
    hooks : SemanticProHooks | None, optional
        Optional injection points for pipeline orchestration. Defaults to the
        production hooks and is primarily used by unit tests.

    Returns
    -------
    AnswerEnvelope
        Search results envelope with chunks, metadata, and method information.

    Notes
    -----
    Exceptions raised during catalog hydration or Stage-0 execution propagate to
    the caller, enabling upstream handlers to convert them into Problem Details
    responses when needed.
    """
    start_time = perf_counter()
    hooks = hooks or _DEFAULT_HOOKS
    stage0_result, metadata = hooks.execute_stage0(
        SemanticStage0Request(
            context=request.context,
            query=request.query,
            limit=request.limit,
            scope=request.scope,
            options=Stage0Options(weights=request.options.stage_weights or None),
        )
    )
    state = _StageState(
        ids=list(stage0_result.ids),
        scores=list(stage0_result.scores),
        limits=[*metadata.limits, *stage0_result.warnings],
    )

    decision = hooks.decide_stage_two(request.context, state.ids, state.scores)

    if request.options.use_warp and decision.should_run:
        late_result = hooks.run_late_interaction(
            request.context,
            request.query,
            state.ids,
            request.options,
        )
        if late_result is not None:
            merged_ids, merged_scores = _merge_late_interaction(
                state.ids, state.scores, late_result
            )
            state.ids = merged_ids
            state.scores = merged_scores
            state.explanations = late_result.explanations
            state.stage1_channel = "xtr"
        else:
            state.limits.append("late_interaction:unavailable")
    else:
        state.limits.append(f"late_interaction_skipped:{decision.reason}")

    if request.options.use_reranker:
        state.ids, state.scores, state.rerank_metadata = hooks.apply_reranker(
            _RerankerRequest(
                context=request.context,
                query=request.query,
                ids=state.ids,
                scores=state.scores,
                options=request.options,
            ),
            _DEFAULT_RERANKER_DEPS,
        )
        if state.rerank_metadata:
            reason = state.rerank_metadata.get("reason")
            if reason:
                state.limits.append(f"rerank:{reason}")

    state.ids = state.ids[: metadata.effective_limit]
    state.scores = state.scores[: metadata.effective_limit]

    findings = hooks.hydrate_findings(
        request.context,
        state.ids,
        state.scores,
        request.scope,
    )
    _annotate_hybrid_contributions(
        findings,
        stage0_result.contributions,
        request.context.settings.index.rrf_k,
    )
    _apply_explainability(findings, state.explanations)

    envelope: AnswerEnvelope = {
        "answer": f"Found {len(findings)} semantic_pro results for: {request.query}",
        "query_kind": "semantic_pro",
        "findings": findings,
        "confidence": float(state.scores[0]) if state.scores else 0.0,
        "method": _compose_method(
            _MethodContext(
                stage0=stage0_result,
                decision=decision,
                stage1_channel=state.stage1_channel,
                rerank_metadata=state.rerank_metadata,
                findings_count=len(findings),
                metadata=metadata,
                requested_limit=request.limit,
                start_time=start_time,
            )
        ),
        "limits": state.limits,
    }
    if request.scope:
        envelope["scope"] = request.scope
    return envelope


def _decide_stage_two(
    context: ApplicationContext,
    ids: Sequence[int],
    scores: Sequence[float],
) -> StageDecision:
    """Decide whether to run secondary stage (late-interaction) based on signals.

    This function determines whether to run the secondary stage (late-interaction
    rescoring) by analyzing candidate count, score margins, and budget constraints.
    The decision is based on adaptive gating logic that evaluates whether late-interaction
    is likely to improve results.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings for CodeRank configuration. Used
        to access min_stage2_candidates, min_stage2_margin, and budget_ms settings.
    ids : Sequence[int]
        Sequence of candidate chunk IDs from Stage-0 retrieval. Used to determine
        candidate count for gating decision.
    scores : Sequence[float]
        Sequence of candidate scores corresponding to IDs. Used to compute score
        margins (top_score - second_score) for gating decision.

    Returns
    -------
    StageDecision
        Decision object indicating whether secondary stage should run, reason for
        the decision, and optional notes. The decision considers candidate count,
        score margins, and budget constraints.

    Notes
    -----
    Stage-2 decision enables adaptive late-interaction by determining when rescoring
    is likely to improve results. The function uses adaptive gating logic that considers
    candidate count (must meet minimum), score margins (high margin suggests confidence),
    and budget constraints (latency limits). This prevents unnecessary late-interaction
    when Stage-0 results are already high-quality.
    """
    config = StageGateConfig(
        min_candidates=context.settings.coderank.min_stage2_candidates,
        margin_threshold=context.settings.coderank.min_stage2_margin,
        budget_ms=context.settings.coderank.budget_ms,
    )
    signals = {
        "candidate_count": len(ids),
        "elapsed_ms": 0.0,
        "top_score": scores[0] if scores else None,
        "second_score": scores[1] if len(scores) > 1 else None,
    }
    return decide_secondary_stage(signals=signals, config=config)


def _maybe_run_late_interaction(
    context: ApplicationContext,
    query: str,
    ids: Sequence[int],
    options: SemanticProRuntimeOptions,
    *,
    index_provider: Callable[[ApplicationContext], XTRIndex | None] | None = None,
) -> LateInteractionResult | None:
    """Run late-interaction rescoring if XTR index is available.

    This function attempts to run late-interaction rescoring using the XTR index
    if it's available and ready. The function handles index unavailability gracefully
    by returning None, enabling the pipeline to continue without late-interaction.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and XTR index access. Used to
        retrieve XTR index and configuration (candidate_k).
    query : str
        Search query text to rescore against. Used for token-level late-interaction
        scoring.
    ids : Sequence[int]
        Sequence of candidate chunk IDs to rescore. The function limits rescoring
        to the configured candidate_k or the number of IDs, whichever is smaller.
    options : SemanticProRuntimeOptions
        Runtime options containing explain flag and optional xtr_k override.
        Used to configure rescoring behavior and explanation generation.
    index_provider : Callable[[ApplicationContext], XTRIndex | None] | None, optional
        Optional function to retrieve XTR index from context. Defaults to
        ApplicationContext.get_xtr_index. Used for dependency injection in tests.

    Returns
    -------
    LateInteractionResult | None
        Late-interaction result containing rescored IDs, scores, and optional
        explanations. Returns None if XTR index is unavailable, not ready,
        or rescoring fails.

    Notes
    -----
    Late-interaction execution enables token-level rescoring by using XTR indexes
    to refine Stage-0 results. The function handles index unavailability gracefully,
    enabling the pipeline to continue without late-interaction when indexes are
    missing or not ready. The function limits rescoring to configured candidate_k
    to manage latency and resource usage.
    """
    provider = index_provider or ApplicationContext.get_xtr_index
    try:
        index = provider(context)
    except RuntimeError:
        return None
    if index is None or not index.ready:
        return None
    k_limit = options.xtr_k or context.settings.xtr.candidate_k
    k = min(max(1, k_limit), len(ids))
    if k <= 0:
        return None
    late = XTRLateInteraction(index)
    return late.rescore(query, ids[:k], explain=options.explain)


def _merge_late_interaction(
    base_ids: Sequence[int],
    base_scores: Sequence[float],
    late_result: LateInteractionResult,
) -> tuple[list[int], list[float]]:
    """Merge late-interaction rescored results with base Stage-0 rankings.

    This function merges late-interaction rescored results with base Stage-0
    rankings by placing rescored candidates first (in their rescored order) and
    appending remaining base candidates that weren't rescored. Duplicate IDs
    are deduplicated, with rescored versions taking precedence.

    Parameters
    ----------
    base_ids : Sequence[int]
        Base candidate chunk IDs from Stage-0 retrieval. These are appended
        after rescored candidates, excluding duplicates.
    base_scores : Sequence[float]
        Base candidate scores corresponding to base_ids. Used to preserve
        scores for candidates that weren't rescored.
    late_result : LateInteractionResult
        Late-interaction result containing rescored IDs and scores. Rescored
        candidates are placed first in the merged output.

    Returns
    -------
    tuple[list[int], list[float]]
        Tuple containing (merged_ids, merged_scores). Merged IDs contain rescored
        candidates first (in rescored order), followed by remaining base candidates
        (excluding duplicates). Merged scores correspond to merged IDs.

    Notes
    -----
    Result merging enables combining late-interaction rescored results with base
    Stage-0 rankings to produce a unified ranking. The function ensures rescored
    candidates take precedence while preserving base candidates that weren't rescored,
    enabling comprehensive result sets that leverage both Stage-0 and late-interaction
    scoring.
    """
    seen: set[int] = set()
    merged_ids: list[int] = []
    merged_scores: list[float] = []

    for chunk_id, score in zip(late_result.ids, late_result.scores, strict=False):
        seen.add(chunk_id)
        merged_ids.append(chunk_id)
        merged_scores.append(score)

    for chunk_id, score in zip(base_ids, base_scores, strict=True):
        if chunk_id in seen:
            continue
        merged_ids.append(chunk_id)
        merged_scores.append(score)

    return merged_ids, merged_scores


def _maybe_apply_reranker(
    request: _RerankerRequest,
    deps: RerankerDependencies | None = None,
) -> tuple[list[int], list[float], MethodRerankerInfo]:
    """Apply optional reranker to reorder search results.

    This function applies an optional listwise reranker (CodeRank LLM) to reorder
    search results based on query-document relevance. The function handles
    reranker unavailability gracefully by returning original rankings with metadata
    indicating why reranking was skipped.

    Parameters
    ----------
    request : _RerankerRequest
        Reranker request object containing context, query, candidate IDs, scores,
        and options. The request encapsulates all inputs needed for reranker execution.
    deps : RerankerDependencies | None, optional
        Optional dependency overrides for adapter construction and document
        fetching. Defaults to production dependencies. Used for dependency
        injection in tests.

    Returns
    -------
    tuple[list[int], list[float], MethodRerankerInfo]
        Tuple containing (reranked_ids, reranked_scores, reranker_metadata).
        Reranked IDs and scores are reordered based on reranker output when
        reranking succeeds, otherwise original IDs and scores are returned.
        Metadata describes reranker execution status and reason for skipping
        if reranking was not performed.

    Notes
    -----
    Reranker application enables listwise reranking by using CodeRank LLM to
    reorder search results based on query-document relevance. The function handles
    reranker unavailability gracefully (disabled config, unsupported provider,
    adapter unavailable, no docs, no rerank results) by returning original rankings
    with appropriate metadata. This ensures robust operation even when reranking
    dependencies are missing or unavailable.
    """
    active_deps = deps or _DEFAULT_RERANKER_DEPS
    provider = "coderank_llm"
    cfg = getattr(request.context.settings, "coderank_llm", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return (
            request.ids,
            request.scores,
            _build_reranker_metadata(
                provider=provider,
                enabled=False,
                reason="disabled_config",
            ),
        )
    if request.options.rerank and request.options.rerank.provider not in {None, provider}:
        return (
            request.ids,
            request.scores,
            _build_reranker_metadata(
                provider=provider,
                enabled=False,
                reason="unsupported_provider",
            ),
        )
    adapter = active_deps.adapter_builder(cfg)
    if adapter is None:
        return (
            request.ids,
            request.scores,
            _build_reranker_metadata(
                provider=provider,
                enabled=False,
                reason="adapter_unavailable",
            ),
        )

    docs = active_deps.doc_fetcher(request.context, request.ids, active_deps.relation_checker)
    if not docs:
        return (
            request.ids,
            request.scores,
            _build_reranker_metadata(
                provider=provider,
                enabled=False,
                reason="no_docs",
            ),
        )

    rerank_opts = request.options.rerank
    top_k = rerank_opts.top_k if rerank_opts and rerank_opts.top_k else len(docs)
    doc_objs = [
        Doc(id=int(doc["id"]), uri=doc.get("uri"), snippet=doc.get("snippet")) for doc in docs
    ]
    rerank_result = adapter.rerank(request.query, doc_objs[:top_k])
    if not rerank_result.ids:
        return (
            request.ids,
            request.scores,
            _build_reranker_metadata(
                provider=provider,
                enabled=False,
                reason="no_rerank",
            ),
        )

    base_scores = dict(zip(request.ids, request.scores, strict=False))
    for chunk_id, delta in zip(rerank_result.ids, rerank_result.scores, strict=False):
        base_scores[chunk_id] = base_scores.get(chunk_id, 0.0) + delta
    ordered = sorted(base_scores.items(), key=lambda item: item[1], reverse=True)
    new_ids = [cid for cid, _ in ordered]
    new_scores = [score for _, score in ordered]
    metadata = _build_reranker_metadata(
        provider=provider,
        enabled=True,
        reordered=len(rerank_result.ids),
    )
    return new_ids, new_scores, metadata


def _build_coderank_adapter(cfg: _CoderankLLMConfig) -> RerankAdapter | None:
    """Build CodeRank LLM adapter from configuration if dependencies are available.

    This function constructs a CodeRankLLMAdapter instance from configuration
    if the required dependencies (CodeRankListwiseReranker, CodeRankGenerationSettings,
    CoderankLLMRerankerContext, CodeRankLLMAdapter) are available. The function
    handles missing dependencies gracefully by returning None.

    Parameters
    ----------
    cfg : _CoderankLLMConfig
        CodeRank LLM configuration object containing model_id, device,
        max_new_tokens, temperature, and top_p settings. Used to configure
        the reranker instance.

    Returns
    -------
    CodeRankLLMAdapter | None
        Configured CodeRank LLM adapter instance ready for listwise reranking.
        Returns None if required dependencies are not available (optional
        dependency not installed).

    Notes
    -----
    Adapter construction enables listwise reranking by configuring a CodeRank
    LLM reranker instance. The function handles missing dependencies gracefully,
    enabling the pipeline to run without reranking when optional dependencies
    are not installed. The adapter uses production context for consistent
    behavior across deployments.
    """
    if (
        CodeRankListwiseReranker is None
        or CodeRankGenerationSettings is None
        or CoderankLLMRerankerContext is None
        or CodeRankLLMAdapter is None
    ):
        return None
    reranker = CodeRankListwiseReranker(
        model_id=cfg.model_id,
        device=cfg.device,
        settings=CodeRankGenerationSettings(
            max_new_tokens=cfg.max_new_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
        ),
        context=CoderankLLMRerankerContext.production(),
    )
    return CodeRankLLMAdapter(reranker)


def _fetch_docs_for_reranker(
    context: ApplicationContext,
    ids: Sequence[int],
    relation_checker: RelationChecker,
) -> list[dict]:
    """Fetch document records for reranker from catalog.

    This function retrieves document records (chunks) from the DuckDB catalog
    for the specified chunk IDs. The function opens a catalog connection, checks
    for chunk relation existence, and fetches records with URI and snippet data.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing catalog access. Used to open catalog
        connection and query chunk records.
    ids : Sequence[int]
        Sequence of chunk IDs to fetch documents for. The function queries
        the catalog for records matching these IDs.
    relation_checker : Callable[[object, str], bool]
        Function to check if a relation exists in the catalog. Used to validate
        that the chunks table exists before querying. Takes a connection object
        and relation name, returns True if relation exists.

    Returns
    -------
    list[dict]
        List of document dictionaries containing "id", "uri", and "snippet" keys.
        Returns empty list if ids is empty or chunks relation doesn't exist.
        Each dictionary contains chunk ID, URI, and preview snippet.

    Notes
    -----
    Document fetching enables reranker operation by providing document content
    (URI and snippets) needed for listwise reranking. The function handles
    missing relations gracefully by returning empty records, enabling robust
    operation even when catalog structure is incomplete. Snippets are truncated
    to SNIPPET_PREVIEW_CHARS for efficiency.
    """
    if not ids:
        return []
    with context.open_catalog() as catalog:
        return _fetch_docs_min(catalog, ids, relation_checker)


def _fetch_docs_min(
    catalog: DuckDBCatalog,
    ids: Sequence[int],
    relation_checker: RelationChecker,
) -> list[dict]:
    """Fetch minimal document records from catalog for reranker.

    This function retrieves minimal document records (chunks) from the DuckDB
    catalog for the specified chunk IDs. The function checks for chunk relation
    existence and fetches records with ID, URI, and snippet data, handling
    missing relations gracefully.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance providing database connection and query methods.
        Used to query chunk records by IDs.
    ids : Sequence[int]
        Sequence of chunk IDs to fetch documents for. The function queries
        the catalog for records matching these IDs.
    relation_checker : Callable[[object, str], bool]
        Function to check if a relation exists in the catalog. Used to validate
        that the chunks table exists before querying. Takes a connection object
        and relation name, returns True if relation exists.

    Returns
    -------
    list[dict]
        List of document dictionaries containing "id", "uri", and "snippet" keys.
        Returns empty list if ids is empty. Returns empty records (id only) if
        chunks relation doesn't exist. Each dictionary contains chunk ID, URI,
        and preview snippet (truncated to SNIPPET_PREVIEW_CHARS).

    Notes
    -----
    Minimal document fetching enables reranker operation by providing essential
    document content (ID, URI, snippets) needed for listwise reranking. The
    function handles missing relations gracefully by returning empty records,
    enabling robust operation even when catalog structure is incomplete. Snippets
    are truncated to SNIPPET_PREVIEW_CHARS to manage memory usage and latency.
    """
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_checker(conn, "chunks"):
            return [{"id": int(i), "uri": "", "snippet": ""} for i in ids]
    records = catalog.query_by_ids(list(ids))
    record_map = {
        int(record["id"]): (
            record.get("uri") or "",
            (record.get("preview") or record.get("content") or "")[:SNIPPET_PREVIEW_CHARS],
        )
        for record in records
        if "id" in record
    }
    return [
        {"id": int(chunk_id), "uri": data[0], "snippet": data[1]}
        for chunk_id in ids
        if (data := record_map.get(int(chunk_id))) is not None
    ]


def _hydrate_findings(
    context: ApplicationContext,
    chunk_ids: Sequence[int],
    scores: Sequence[float],
    scope: ScopeIn | None,
) -> list[Finding]:
    """Hydrate chunk IDs and scores into Finding objects with metadata.

    This function converts chunk IDs and scores into Finding objects by querying
    the catalog for chunk metadata (URI, content, line ranges) and structure
    annotations. The function applies scope filters if provided and constructs
    Finding objects with location, snippet, score, and explanation data.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing catalog access. Used to open catalog
        connection and query chunk records and structure annotations.
    chunk_ids : Sequence[int]
        Sequence of chunk IDs to hydrate into findings. The function queries
        the catalog for records matching these IDs.
    scores : Sequence[float]
        Sequence of scores corresponding to chunk_ids. Used to populate finding
        score fields. Must have same length as chunk_ids.
    scope : ScopeIn | None
        Optional scope filters for limiting search results. If provided, the
        function applies include_globs, exclude_globs, and languages filters
        when querying chunks.

    Returns
    -------
    list[Finding]
        List of Finding objects containing type, title, location, snippet, score,
        chunk_id, and explanations. Returns empty list if chunk_ids is empty.
        Findings are ordered to match chunk_ids and scores sequences.

    Notes
    -----
    Finding hydration enables result presentation by converting raw chunk IDs
    and scores into rich Finding objects with metadata. The function applies
    scope filters when provided, enabling focused search results. Structure
    annotations are included to provide explainability for why chunks matched
    the query. Snippets are truncated to SNIPPET_PREVIEW_CHARS for efficiency.
    """
    if not chunk_ids:
        return []

    with context.open_catalog() as catalog:
        include_globs = scope.get("include_globs") if scope else None
        exclude_globs = scope.get("exclude_globs") if scope else None
        languages = scope.get("languages") if scope else None
        filters_active = bool(include_globs or exclude_globs or languages)

        if filters_active:
            records = catalog.query_by_filters(
                chunk_ids,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                languages=languages,
            )
        else:
            records = catalog.query_by_ids(chunk_ids)
        record_map = {int(record["id"]): record for record in records if "id" in record}
        annotations = catalog.get_structure_annotations(chunk_ids)

    findings: list[Finding] = []
    for chunk_id, score in zip(chunk_ids, scores, strict=True):
        record = record_map.get(int(chunk_id))
        if not record:
            continue
        snippet = (record.get("content") or record.get("preview") or "")[:SNIPPET_PREVIEW_CHARS]
        finding: Finding = {
            "type": "usage",
            "title": f"{Path(record['uri']).name} (score: {score:.3f})",
            "location": {
                "uri": record["uri"],
                "start_line": int(record.get("start_line") or 0),
                "start_column": 0,
                "end_line": int(record.get("end_line") or 0),
                "end_column": 0,
            },
            "snippet": snippet,
            "score": float(score),
            "chunk_id": int(chunk_id),
            "explanations": _structure_explanations(annotations.get(int(chunk_id))),
        }
        findings.append(finding)
    return findings


def _structure_explanations(annotation: StructureAnnotations | None) -> ExplanationPayload:
    """Convert structure annotations into explanation payload format.

    This function transforms structure annotations (symbol hits, AST node kinds,
    CST matches) into an ExplanationPayload dictionary suitable for inclusion in
    Finding objects. The function handles None annotations gracefully by returning
    empty explanation payload.

    Parameters
    ----------
    annotation : StructureAnnotations | None
        Structure annotation object containing symbol hits, AST node kinds, and
        CST matches. If None, returns empty explanation payload.

    Returns
    -------
    ExplanationPayload
        Explanation payload dictionary containing matched_symbols (list of symbol
        names), ast_kind (first AST node kind or None), and cst_hits (list of
        CST matches or empty list). Returns empty payload if annotation is None.

    Notes
    -----
    Explanation conversion enables explainability by transforming structured
    annotation data into a format suitable for Finding objects. The function
    extracts symbol hits, AST node kinds, and CST matches, enabling users to
    understand why chunks matched queries based on code structure and symbols.
    Empty annotations are handled gracefully to support chunks without structure
    metadata.
    """
    if annotation is None:
        return {
            "matched_symbols": [],
            "ast_kind": None,
            "cst_hits": [],
        }
    matched = list(annotation.symbol_hits)
    ast_kind = annotation.ast_node_kinds[0] if annotation.ast_node_kinds else None
    cst_hits = list(annotation.cst_matches) if annotation.cst_matches else []
    return {
        "matched_symbols": matched,
        "ast_kind": ast_kind,
        "cst_hits": cst_hits,
    }


def _apply_explainability(
    findings: list[Finding],
    explainability: Sequence[tuple[int, dict[str, Any]]] | None,
) -> None:
    """Apply explainability annotations to findings from late-interaction results.

    This function enriches Finding objects with explainability annotations from
    late-interaction rescoring results. The function appends token alignment
    information to finding "why" fields, enabling users to understand how query
    tokens aligned with document tokens during rescoring.

    Parameters
    ----------
    findings : list[Finding]
        List of Finding objects to annotate with explainability information.
        Findings are modified in-place by updating their "why" fields.
    explainability : Sequence[tuple[int, dict[str, Any]]] | None
        Optional sequence of (chunk_id, explanation_dict) tuples from late-interaction
        rescoring. Each explanation dictionary contains token_matches with query
        and document token alignment information. If None, no annotations are applied.

    Notes
    -----
    Explainability application enables detailed result explanations by enriching
    findings with token-level alignment information from late-interaction rescoring.
    The function appends alignment summaries to existing "why" fields, enabling
    users to understand how query tokens matched document tokens. Token matches
    are formatted as "q{query_index}→d{doc_index}={similarity}" for readability.
    """
    if not explainability:
        return
    lookup = dict(explainability)
    for finding in findings:
        chunk_id = finding.get("chunk_id")
        if chunk_id is None or chunk_id not in lookup:
            continue
        payload = lookup[chunk_id]
        matches = payload.get("token_matches")
        if not matches:
            continue
        summary = ", ".join(
            f"q{match['q_index']}→d{match['doc_index']}={match['similarity']:.2f}"
            for match in matches
        )
        prior = finding.get("why")
        finding["why"] = (
            f"{prior}; XTR alignments: {summary}" if prior else f"XTR alignments: {summary}"
        )


@dataclass(slots=True, frozen=True)
class _MethodContext:
    """Bundle inputs required to build the method metadata block."""

    stage0: Stage0Result
    decision: StageDecision
    stage1_channel: str | None
    rerank_metadata: MethodRerankerInfo | None
    findings_count: int
    metadata: Stage0Metadata
    requested_limit: int
    start_time: float


def _build_gating_metadata(decision: StageDecision) -> MethodGatingInfo:
    """Return metadata describing whether the secondary stage executed.

    Returns
    -------
    MethodGatingInfo
        Typed metadata block describing the gating decision and optional notes.
    """
    payload: MethodGatingInfo = {
        "should_run_secondary_stage": decision.should_run,
        "reason": decision.reason,
    }
    if decision.notes:
        payload["notes"] = list(decision.notes)
    return payload


def _build_reranker_metadata(
    *,
    provider: str | None,
    enabled: bool,
    reason: str | None = None,
    reordered: int | None = None,
) -> MethodRerankerInfo:
    """Return reranker metadata with optional reason and reorder count.

    Returns
    -------
    MethodRerankerInfo
        Metadata dictionary specifying provider, enablement, optional reason,
        and number of reordered documents.
    """
    payload: MethodRerankerInfo = {
        "provider": provider,
        "enabled": enabled,
    }
    if reason is not None:
        payload["reason"] = reason
    if reordered is not None:
        payload["reordered"] = reordered
    return payload


def _compose_method(
    context: _MethodContext,
) -> MethodInfo:
    """Compose method metadata from pipeline execution context.

    This function constructs a MethodInfo dictionary from pipeline execution
    context, including retrieval channels, coverage string, Stage-0 metadata,
    gating information, and reranker metadata. The method info describes how
    search results were generated.

    Parameters
    ----------
    context : _MethodContext
        Method context object containing Stage-0 result, stage decision,
        stage1 channel, reranker metadata, findings count, Stage-0 metadata,
        requested limit, and start time. Used to compose comprehensive method
        metadata.

    Returns
    -------
    MethodInfo
        Method metadata dictionary containing retrieval channels, coverage string,
        Stage-0 method details, gating information, and reranker metadata. The
        coverage string includes findings count, effective limit, elapsed time,
        and requested limit if different.

    Notes
    -----
    Method composition enables comprehensive result metadata by combining information
    from all pipeline stages (Stage-0, late-interaction, reranking) into a single
    metadata dictionary. The function constructs retrieval channel lists, coverage
    strings with timing information, and includes gating and reranker metadata to
    provide complete visibility into how results were generated.
    """
    retrieval = list(context.stage0.channels or ["semantic"])
    if context.stage1_channel:
        retrieval = list(dict.fromkeys([*retrieval, context.stage1_channel]))
    elapsed_ms = int((perf_counter() - context.start_time) * 1000)
    coverage = (
        f"{context.findings_count}/{context.metadata.effective_limit} results in {elapsed_ms}ms"
    )
    if context.requested_limit != context.metadata.effective_limit:
        coverage = f"{coverage} (requested {context.requested_limit})"
    return MethodInfoComponents(
        retrieval_channels=retrieval,
        coverage=coverage,
        stage0=context.stage0.method,
        gating=_build_gating_metadata(context.decision),
        reranker=context.rerank_metadata,
    ).as_method_info()


def _annotate_hybrid_contributions(
    findings: list[Finding],
    contribution_map: Mapping[int, list[tuple[str, int, float]]] | None,
    rrf_k: int,
) -> None:
    """Annotate findings with hybrid retrieval channel contribution information.

    This function enriches Finding objects with hybrid retrieval channel contribution
    information from Stage-0 RRF fusion. The function appends contribution summaries
    to finding "why" fields, enabling users to understand which retrieval channels
    (semantic, BM25, SPLADE) contributed to each result.

    Parameters
    ----------
    findings : list[Finding]
        List of Finding objects to annotate with hybrid contributions. Findings
        are modified in-place by updating their "why" fields.
    contribution_map : Mapping[int, list[tuple[str, int, float]]] | None
        Optional mapping from chunk IDs to lists of channel contributions. Each
        contribution is a tuple of (channel_name, rank, score). If None, no
        annotations are applied.
    rrf_k : int
        RRF fusion K parameter used for score normalization. Used to compute
        normalized contribution scores for display.

    Notes
    -----
    Contribution annotation enables explainability by enriching findings with
    channel-level contribution information from hybrid retrieval. The function
    appends contribution summaries to existing "why" fields, enabling users to
    understand which retrieval channels contributed to each result and their
    relative importance. Contributions are formatted as "channel:rank=score"
    for readability, with scores normalized using RRF K parameter.
    """
    if not contribution_map:
        return
    for finding in findings:
        chunk_id_value = finding.get("chunk_id")
        if chunk_id_value is None:
            continue
        contributions = contribution_map.get(int(chunk_id_value))
        if not contributions:
            continue
        parts = [f"{channel} rank={rank}" for channel, rank, _ in contributions]
        finding["why"] = f"Hybrid RRF (k={rrf_k}): " + ", ".join(parts)


def build_semantic_pro_hooks(
    *,
    execute_stage0: Callable[
        [SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]
    ] = execute_semantic_stage0,
    decide_stage_two: Callable[
        [ApplicationContext, Sequence[int], Sequence[float]], StageDecision
    ] = _decide_stage_two,
    run_late_interaction: Callable[
        [ApplicationContext, str, Sequence[int], SemanticProRuntimeOptions],
        LateInteractionResult | None,
    ] = _maybe_run_late_interaction,
    apply_reranker: Callable[
        [_RerankerRequest, RerankerDependencies | None],
        tuple[list[int], list[float], MethodRerankerInfo],
    ] = _maybe_apply_reranker,
    hydrate_findings: Callable[
        [ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None],
        list[Finding],
    ] = _hydrate_findings,
) -> SemanticProHooks:
    """Return hooks for overriding semantic_pro orchestration steps.

    Parameters
    ----------
    execute_stage0 : Callable[[SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]]
        Replacement for :func:`execute_semantic_stage0`.
    decide_stage_two : Callable[[ApplicationContext, Sequence[int], Sequence[float]], StageDecision]
        Override for the Stage-1 gating decision helper.
    run_late_interaction : Callable[[ApplicationContext, str, Sequence[int], SemanticProRuntimeOptions], LateInteractionResult | None]
        Custom runner for XTR late interaction.
    apply_reranker : Callable[[ApplicationContext, str, list[int], list[float], SemanticProRuntimeOptions], tuple[list[int], list[float], MethodRerankerInfo]]
        Override for reranker orchestration and score merging.
    hydrate_findings : Callable[[ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None], list[Finding]]
        Hydration helper for turning chunk IDs into findings.

    Returns
    -------
    SemanticProHooks
        Hooks object with the provided overrides (falling back to production defaults).
    """
    return SemanticProHooks(
        execute_stage0=execute_stage0,
        decide_stage_two=decide_stage_two,
        run_late_interaction=run_late_interaction,
        apply_reranker=apply_reranker,
        hydrate_findings=hydrate_findings,
    )


_DEFAULT_HOOKS = build_semantic_pro_hooks()
_DEFAULT_ASYNC_DEPS = build_async_dependencies()
_DEFAULT_RERANKER_DEPS = RerankerDependencies(
    adapter_builder=_build_coderank_adapter,
    doc_fetcher=_fetch_docs_for_reranker,
    relation_checker=relation_exists,
)


def build_reranker_dependencies(
    *,
    adapter_builder: Callable[
        [_CoderankLLMConfig], RerankAdapter | None
    ] = _build_coderank_adapter,
    doc_fetcher: Callable[
        [ApplicationContext, Sequence[int], RelationChecker], list[dict]
    ] = _fetch_docs_for_reranker,
    relation_checker: RelationChecker = relation_exists,
) -> RerankerDependencies:
    """Return dependency overrides for reranker orchestration.

    Parameters
    ----------
    adapter_builder : Callable[[_CoderankLLMConfig], _RerankAdapter | None], optional
        Optional function to override adapter construction. Defaults to
        _build_coderank_adapter. Used for dependency injection in tests.
    doc_fetcher : Callable[[ApplicationContext, Sequence[int], RelationChecker], list[dict]], optional
        Optional function to override document fetching. Defaults to
        _fetch_docs_for_reranker. Used for dependency injection in tests.
    relation_checker : RelationChecker, optional
        Optional function to override relation existence checking. Defaults to
        relation_exists. Used for dependency injection in tests.

    Returns
    -------
    RerankerDependencies
        Dependencies object with the provided overrides (falling back to
        production defaults).
    """
    return RerankerDependencies(
        adapter_builder=adapter_builder,
        doc_fetcher=doc_fetcher,
        relation_checker=relation_checker,
    )
