"""Two-stage semantic search (CodeRank → optional WARP → optional reranker)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, TypedDict

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.io.coderank_embedder import CodeRankEmbedder
from codeintel_rev.io.rerank_coderankllm import CodeRankListwiseReranker
from codeintel_rev.io.rrf import weighted_rrf
from codeintel_rev.io.warp_engine import WarpEngine, WarpUnavailableError
from codeintel_rev.mcp_server.common.observability import observe_duration
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, Finding, MethodInfo, ScopeIn
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from kgfoundry_common.errors import EmbeddingError, VectorSearchError
from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import DurationObservation

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SNIPPET_PREVIEW_CHARS = 500
COMPONENT_NAME = "codeintel_mcp"
LOGGER = get_logger(__name__)


class SemanticProOptions(TypedDict, total=False):
    """User-facing options for semantic_pro retrieval."""

    use_coderank: bool
    use_warp: bool
    use_reranker: bool
    stage_weights: dict[str, float]
    explain: bool


@dataclass(frozen=True)
class SemanticProRuntimeOptions:
    """Internal immutable representation of semantic_pro options."""

    use_coderank: bool = True
    use_warp: bool = True
    use_reranker: bool = False
    stage_weights: dict[str, float] = field(default_factory=dict)
    explain: bool = True


def build_runtime_options(options: SemanticProOptions | None) -> SemanticProRuntimeOptions:
    """Normalize user-supplied options into an immutable dataclass."""
    if options is None:
        return SemanticProRuntimeOptions()
    return SemanticProRuntimeOptions(
        use_coderank=options.get("use_coderank", True),
        use_warp=options.get("use_warp", True),
        use_reranker=options.get("use_reranker", False),
        stage_weights=dict(options.get("stage_weights", {})),
        explain=options.get("explain", True),
    )


async def semantic_search_pro(
    context: ApplicationContext,
    *,
    query: str,
    limit: int,
    options: SemanticProOptions | None = None,
) -> AnswerEnvelope:
    """Async wrapper that executes the two-stage retrieval pipeline.

    Returns
    -------
    AnswerEnvelope
        Search results with metadata and optional explanations.
    """
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
    with observe_duration("semantic_search_pro", COMPONENT_NAME) as observation:
        effective_limit, limit_notes = _clamp_limit(limit, context.settings.limits.max_results)
        coderank_hits = _run_coderank_stage(
            context=context,
            query=query,
            fanout=max(
                effective_limit,
                effective_limit * context.settings.limits.semantic_overfetch_multiplier,
            ),
            observation=observation,
        )

        warp_notes: list[str] = []
        warp_hits: list[tuple[int, float]] = []
        channels_used: list[str] = ["coderank"]
        if coderank_hits and options.use_warp and context.settings.warp.enabled:
            warp_hits, warp_notes = _run_warp_stage(
                context=context,
                query=query,
                candidates=coderank_hits,
            )
            if warp_hits:
                channels_used.append("warp")
        elif options.use_warp and not context.settings.warp.enabled:
            warp_notes.append("WARP disabled via configuration flag.")

        ordered_ids, contribution_map, score_map = _fuse_channels(
            coderank_hits=coderank_hits,
            warp_hits=warp_hits,
            weights=_merge_stage_weights(options.stage_weights),
            rrf_k=context.settings.index.rrf_k,
            fusion_limit=max(
                effective_limit,
                effective_limit * context.settings.limits.semantic_overfetch_multiplier,
            ),
        )

        if not ordered_ids:
            observation.mark_success()
            extras = _build_envelope_extras(
                findings_count=0,
                requested=limit,
                effective=effective_limit,
                start_time=start_time,
                channels=channels_used,
                limits=limit_notes + warp_notes,
                scope=scope,
            )
            return _make_envelope(
                answer=f"No results found for: {query}",
                findings=[],
                extras=extras,
            )

        deduped_ids = _dedupe_preserve_order(ordered_ids)
        hydration_limit = min(len(deduped_ids), max(effective_limit * 2, effective_limit))
        try:
            chunk_records = _hydrate_records(
                context=context,
                chunk_ids=deduped_ids[:hydration_limit],
                scope=scope,
            )
        except (RuntimeError, OSError) as exc:
            observation.mark_error()
            msg = "DuckDB hydration failed"
            raise VectorSearchError(msg, cause=exc) from exc

        reranked_records = _maybe_rerank(
            query=query,
            records=chunk_records,
            context=context,
            enabled=options.use_reranker,
        )

        findings = _build_findings(
            records=reranked_records[:effective_limit],
            score_map=score_map,
            contribution_map=contribution_map,
            explain=options.explain,
        )
        observation.mark_success()

        extras = _build_envelope_extras(
            findings_count=len(findings),
            requested=limit,
            effective=effective_limit,
            start_time=start_time,
            channels=channels_used,
            limits=limit_notes + warp_notes,
            scope=scope,
        )

        return _make_envelope(
            answer=f"Found {len(findings)} semantic_pro results for: {query}",
            findings=findings,
            extras=extras,
        )


def _run_coderank_stage(
    *,
    context: ApplicationContext,
    query: str,
    fanout: int,
    observation: DurationObservation,
) -> list[tuple[int, float]]:
    if not context.paths.coderank_faiss_index.exists():
        observation.mark_error()
        msg = "CodeRank FAISS index not found; build it via `python coderank.py build-index`."
        raise VectorSearchError(
            msg,
            context={"coderank_faiss_index": str(context.paths.coderank_faiss_index)},
        )

    cfg = context.settings.coderank
    embedder = CodeRankEmbedder(
        model_id=cfg.model_id,
        device=cfg.device,
        trust_remote_code=cfg.trust_remote_code,
        query_prefix=cfg.query_prefix,
        normalize=cfg.normalize,
        batch_size=cfg.batch_size,
    )
    try:
        query_vec = embedder.encode_queries([query])
    except Exception as exc:
        observation.mark_error()
        msg = f"CodeRank embedding failed: {exc}"
        raise EmbeddingError(
            msg,
            context={"model_id": cfg.model_id, "device": cfg.device},
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


def _run_warp_stage(
    *,
    context: ApplicationContext,
    query: str,
    candidates: list[tuple[int, float]],
) -> tuple[list[tuple[int, float]], list[str]]:
    notes: list[str] = []
    cfg = context.settings.warp
    try:
        warp_engine = WarpEngine(
            index_dir=context.paths.warp_index_dir,
            device=cfg.device,
        )
    except WarpUnavailableError as exc:
        notes.append(str(exc))
        return [], notes

    try:
        hits = warp_engine.rerank(
            query=query,
            candidate_ids=[cid for cid, _ in candidates],
            top_k=min(cfg.top_k, len(candidates)),
        )
    except WarpUnavailableError as exc:
        notes.append(str(exc))
        hits = []
    return hits, notes


def _fuse_channels(
    *,
    coderank_hits: list[tuple[int, float]],
    warp_hits: list[tuple[int, float]],
    weights: dict[str, float],
    rrf_k: int,
    fusion_limit: int,
) -> tuple[list[int], dict[int, list[tuple[str, int, float]]], dict[int, float]]:
    fusion_limit = max(1, fusion_limit)

    if coderank_hits and warp_hits:
        channel_map = {"coderank": coderank_hits, "warp": warp_hits}
        fused_ids, contrib_map, score_map = weighted_rrf(
            channel_map,
            weights=weights,
            k=rrf_k,
            top_k=min(fusion_limit, len(coderank_hits)),
        )
        return fused_ids, contrib_map, score_map

    contrib_map: dict[int, list[tuple[str, int, float]]] = {}
    score_map: dict[int, float] = {}
    ordered = coderank_hits[:fusion_limit]
    ordered_ids = [cid for cid, _ in ordered]
    for rank, (cid, score) in enumerate(ordered, start=1):
        contrib_map.setdefault(cid, []).append(("coderank", rank, score))
        score_map[cid] = score
    return ordered_ids, contrib_map, score_map


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
        (int(record.get("id", -1)), (record.get("content") or record.get("preview") or ""))
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
    score_map: dict[int, float],
    contribution_map: dict[int, list[tuple[str, int, float]]],
    explain: bool,
) -> list[Finding]:
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
        if explain and chunk_id in contribution_map:
            parts = [
                f"{channel} rank={rank}" for channel, rank, _score in contribution_map[chunk_id]
            ]
            finding["why"] = f"Fusion weights: {', '.join(parts)}"
        findings.append(finding)
    return findings


def _build_envelope_extras(
    *,
    findings_count: int,
    requested: int,
    effective: int,
    start_time: float,
    channels: list[str],
    limits: list[str],
    scope: ScopeIn | None,
) -> dict[str, object]:
    method = _build_method(
        findings_count=findings_count,
        requested_limit=requested,
        effective_limit=effective,
        start_time=start_time,
        channels=channels,
    )
    extras: dict[str, object] = {"method": method}
    if limits:
        extras["limits"] = limits
    if scope:
        extras["scope"] = scope
    return extras


def _build_method(
    *,
    findings_count: int,
    requested_limit: int,
    effective_limit: int,
    start_time: float,
    channels: list[str],
) -> MethodInfo:
    elapsed_ms = int((perf_counter() - start_time) * 1000)
    coverage = f"{findings_count}/{effective_limit} results in {elapsed_ms}ms"
    if requested_limit != effective_limit:
        coverage = f"{coverage} (requested {requested_limit})"
    return {
        "retrieval": list(dict.fromkeys(channels)),
        "coverage": coverage,
    }


def _make_envelope(
    *,
    answer: str,
    findings: list[Finding],
    extras: dict[str, object],
) -> AnswerEnvelope:
    envelope: AnswerEnvelope = {
        "answer": answer,
        "query_kind": "semantic_pro",
        "findings": findings,
        "confidence": 0.9 if findings else 0.0,
    }
    envelope.update(extras)
    return envelope


def _clamp_limit(requested: int, max_results: int) -> tuple[int, list[str]]:
    notes: list[str] = []
    if requested <= 0:
        notes.append("Requested limit <= 0; defaulting to 1.")
    if requested > max_results:
        notes.append(f"Requested limit {requested} exceeds max_results {max_results}; truncating.")
    effective = requested
    if effective <= 0:
        effective = 1
    effective = min(effective, max_results)
    return effective, notes


def _merge_stage_weights(stage_weights: dict[str, float]) -> dict[str, float]:
    weights = {"coderank": 1.0, "warp": 1.0}
    for channel, raw in stage_weights.items():
        try:
            weights[channel] = float(raw)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Ignoring non-numeric stage weight",
                extra={"channel": channel, "value": raw},
            )
    return weights


def _dedupe_preserve_order(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for chunk_id in ids:
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        ordered.append(chunk_id)
    return ordered
