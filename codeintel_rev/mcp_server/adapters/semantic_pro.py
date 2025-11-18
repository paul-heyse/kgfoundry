"""Two-stage semantic search adapter built on the retrieval pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations, relation_exists
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ExplanationPayload, Finding, ScopeIn
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from codeintel_rev.retrieval.pipeline import (
    Doc,
    StageDecision,
    StageGateConfig,
    XTRLateInteraction,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import CodeRankLLMAdapter
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Metadata,
    Stage0Options,
    Stage0Result,
    execute_semantic_stage0,
)
from kgfoundry_common.errors import VectorSearchError

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

try:
    from codeintel_rev.io.rerank_coderankllm import (
        CodeRankGenerationSettings,
        CodeRankListwiseReranker,
        CoderankLLMRerankerContext,
    )
except ImportError:  # pragma: no cover - optional dependency
    CodeRankGenerationSettings = None  # type: ignore[assignment]
    CodeRankListwiseReranker = None  # type: ignore[assignment]
    CoderankLLMRerankerContext = None  # type: ignore[assignment]

SNIPPET_PREVIEW_CHARS = 500


class _CoderankLLMConfig(Protocol):
    """Protocol for CodeRank LLM configuration object."""

    model_id: str
    device: str
    max_new_tokens: int
    temperature: float
    top_p: float


class RerankOptionPayload(dict):
    """User-facing payload for overruling rerank behavior."""


class SemanticProOptions(dict):
    """User-facing options for semantic_pro retrieval."""


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
class SemanticRequestContext:
    """Session context supplied by callers (optional)."""

    session_id: str | None = None
    scope: ScopeIn | None = None


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
    request_context: SemanticRequestContext | None = None,
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
    request_context : SemanticRequestContext | None, optional
        Optional request context with session ID and scope.

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
    session = request_context.session_id if request_context else None
    session = session or get_session_id()
    scope = request_context.scope if request_context else None
    if scope is None:
        scope = await get_effective_scope(context, session)

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
    """Execute synchronous semantic search orchestration.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and managers.
    query : str
        Search query text.
    limit : int
        Maximum number of results to return.
    scope : ScopeIn | None
        Optional scope filters for limiting search results.
    options : SemanticProRuntimeOptions
        Runtime options for tuning search behavior.

    Returns
    -------
    AnswerEnvelope
        Search results envelope with chunks, metadata, and method information.
    """
    start_time = perf_counter()
    stage0_options = Stage0Options(weights=options.stage_weights or None)
    stage0_result, metadata = execute_semantic_stage0(
        SemanticStage0Request(
            context=context,
            query=query,
            limit=limit,
            scope=scope,
            options=stage0_options,
        )
    )
    ids = list(stage0_result.ids)
    scores = list(stage0_result.scores)

    decision = _decide_stage_two(context, ids, scores)
    limits = [*metadata.limits, *stage0_result.warnings]
    stage1_channel: str | None = None
    explanations: list[tuple[int, dict[str, Any]]] | None = None

    if options.use_warp and decision.should_run:
        late_result = _maybe_run_late_interaction(context, query, ids, options)
        if late_result is not None:
            ids, scores = _merge_late_interaction(ids, scores, late_result)
            explanations = late_result.explanations
            stage1_channel = "xtr"
        else:
            limits.append("late_interaction:unavailable")
    else:
        limits.append(f"late_interaction_skipped:{decision.reason}")

    rerank_metadata: Mapping[str, Any] | None = None
    if options.use_reranker:
        ids, scores, rerank_metadata = _maybe_apply_reranker(context, query, ids, scores, options)
        if rerank_metadata and rerank_metadata.get("reason"):
            limits.append(f"rerank:{rerank_metadata['reason']}")

    ids = ids[: metadata.effective_limit]
    scores = scores[: metadata.effective_limit]

    findings = _hydrate_findings(context, ids, scores, scope)
    _annotate_hybrid_contributions(
        findings,
        stage0_result.contributions,
        context.settings.index.rrf_k,
    )
    _apply_explainability(findings, explanations)

    method = _compose_method(
        _MethodContext(
            stage0=stage0_result,
            decision=decision,
            stage1_channel=stage1_channel,
            rerank_metadata=rerank_metadata,
            findings_count=len(findings),
            metadata=metadata,
            requested_limit=limit,
            start_time=start_time,
        )
    )

    envelope: AnswerEnvelope = {
        "answer": f"Found {len(findings)} semantic_pro results for: {query}",
        "query_kind": "semantic_pro",
        "findings": findings,
        "confidence": float(scores[0]) if scores else 0.0,
        "method": method,
        "limits": limits,
    }
    if scope:
        envelope["scope"] = scope
    return envelope


def _decide_stage_two(
    context: ApplicationContext,
    ids: Sequence[int],
    scores: Sequence[float],
) -> StageDecision:
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
) -> LateInteractionResult | None:
    try:
        index = context.get_xtr_index()
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
    context: ApplicationContext,
    query: str,
    ids: list[int],
    scores: list[float],
    options: SemanticProRuntimeOptions,
) -> tuple[list[int], list[float], Mapping[str, Any] | None]:
    metadata: dict[str, Any] = {"provider": "coderank_llm", "enabled": False}
    cfg = getattr(context.settings, "coderank_llm", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        metadata["reason"] = "disabled_config"
        return ids, scores, metadata
    if options.rerank and options.rerank.provider not in {None, "coderank_llm"}:
        metadata["reason"] = "unsupported_provider"
        return ids, scores, metadata
    adapter = _build_coderank_adapter(cfg)
    if adapter is None:
        metadata["reason"] = "adapter_unavailable"
        return ids, scores, metadata

    docs = _fetch_docs_for_reranker(context, ids)
    if not docs:
        metadata["reason"] = "no_docs"
        return ids, scores, metadata

    top_k = options.rerank.top_k if options.rerank and options.rerank.top_k else len(docs)
    doc_objs = [
        Doc(id=int(doc["id"]), uri=doc.get("uri"), snippet=doc.get("snippet")) for doc in docs
    ]
    rerank_result = adapter.rerank(query, doc_objs[:top_k])
    if not rerank_result.ids:
        metadata["reason"] = "no_rerank"
        return ids, scores, metadata

    base_scores = dict(zip(ids, scores, strict=False))
    for chunk_id, delta in zip(rerank_result.ids, rerank_result.scores, strict=False):
        base_scores[chunk_id] = base_scores.get(chunk_id, 0.0) + delta
    ordered = sorted(base_scores.items(), key=lambda item: item[1], reverse=True)
    new_ids = [cid for cid, _ in ordered]
    new_scores = [score for _, score in ordered]
    metadata["enabled"] = True
    metadata["reordered"] = len(rerank_result.ids)
    return new_ids, new_scores, metadata


def _build_coderank_adapter(cfg: _CoderankLLMConfig) -> CodeRankLLMAdapter | None:
    if (
        CodeRankListwiseReranker is None
        or CodeRankGenerationSettings is None
        or CoderankLLMRerankerContext is None
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


def _fetch_docs_for_reranker(context: ApplicationContext, ids: Sequence[int]) -> list[dict]:
    if not ids:
        return []
    with context.open_catalog() as catalog:
        return _fetch_docs_min(catalog, ids)


def _fetch_docs_min(catalog: DuckDBCatalog, ids: Sequence[int]) -> list[dict]:
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_exists(conn, "chunks"):
            return [{"id": int(i), "uri": "", "snippet": ""} for i in ids]
        placeholders = ", ".join(["?"] * len(ids))
        table = conn.execute(
            f"SELECT id, uri, preview FROM chunks WHERE id IN ({placeholders})",
            list(ids),
        ).fetch_arrow_table()
        by_id = {
            int(table.column(0)[row].as_py()): (
                table.column(1)[row].as_py(),
                (table.column(2)[row].as_py() or "")[:SNIPPET_PREVIEW_CHARS],
            )
            for row in range(table.num_rows)
        }
        return [
            {"id": int(chunk_id), "uri": record[0], "snippet": record[1]}
            for chunk_id in ids
            if (record := by_id.get(int(chunk_id))) is not None
        ]


def _hydrate_findings(
    context: ApplicationContext,
    chunk_ids: Sequence[int],
    scores: Sequence[float],
    scope: ScopeIn | None,
) -> list[Finding]:
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
    rerank_metadata: Mapping[str, Any] | None
    findings_count: int
    metadata: Stage0Metadata
    requested_limit: int
    start_time: float


def _compose_method(
    context: _MethodContext,
) -> Mapping[str, Any]:
    retrieval = list(context.stage0.channels or ["semantic"])
    if context.stage1_channel:
        retrieval = list(dict.fromkeys([*retrieval, context.stage1_channel]))
    elapsed_ms = int((perf_counter() - context.start_time) * 1000)
    coverage = f"{context.findings_count}/{context.metadata.effective_limit} results in {elapsed_ms}ms"
    if context.requested_limit != context.metadata.effective_limit:
        coverage = f"{coverage} (requested {context.requested_limit})"
    method: dict[str, Any] = {
        "retrieval": retrieval,
        "coverage": coverage,
        "stage0": context.stage0.method or {},
        "gating": {
            "should_run_secondary_stage": context.decision.should_run,
            "reason": context.decision.reason,
        },
    }
    if context.decision.notes:
        method["gating"]["notes"] = list(context.decision.notes)
    if context.rerank_metadata:
        method["reranker"] = context.rerank_metadata
    return method


def _annotate_hybrid_contributions(
    findings: list[Finding],
    contribution_map: Mapping[int, list[tuple[str, int, float]]] | None,
    rrf_k: int,
) -> None:
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
