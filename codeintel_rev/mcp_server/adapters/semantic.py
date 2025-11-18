"""Thin semantic search adapter that delegates to the retrieval pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    Finding,
    MethodGatingInfo,
    MethodInfo,
    Stage0MethodInfo,
)
from codeintel_rev.retrieval.pipeline.gating import (
    StageDecision,
    StageGateConfig,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result, run_stage0

_VIEW_CHUNKS = "chunks"


async def semantic_search(
    context: ApplicationContext, query: str, limit: int = 20
) -> AnswerEnvelope:
    """Execute Stage-0 hybrid retrieval and hydrate findings from DuckDB.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings and metadata.
    """
    return await asyncio.to_thread(_semantic_search_sync, context, query, limit)


def _semantic_search_sync(context: ApplicationContext, query: str, limit: int) -> AnswerEnvelope:
    text = (query or "").strip()
    if not text:
        return _error_envelope("missing query text")

    ready, readiness_limits, _ = context.ensure_faiss_ready()
    try:
        stage0 = run_stage0(
            context.get_hybrid_engine(),
            query=text,
            semantic_hits=[],
            limit=int(limit),
            options=Stage0Options(weights=None, faiss_ready=ready),
        )
    except RuntimeError as exc:
        stage0 = Stage0Result(
            ids=[],
            scores=[],
            warnings=["faiss_fallback:unavailable"],
            method={"error": str(exc)},
        )

    with context.open_catalog() as catalog:
        findings = _hydrate_findings(catalog, stage0.ids, stage0.scores)

    decision = decide_secondary_stage(
        {
            "candidate_count": len(stage0.ids),
            "top_score": stage0.scores[0] if stage0.scores else 0.0,
            "margin": (stage0.scores[0] - stage0.scores[1]) if len(stage0.scores) > 1 else 0.0,
            "budget_ms": 0,
        },
        StageGateConfig(),
    )

    method = _build_method(stage0, decision)
    confidence = float(stage0.scores[0]) if stage0.scores else 0.0
    limits = [f"k={int(limit)}"]
    limits.extend(readiness_limits)
    warning_entries = list(stage0.warnings)
    limits.extend(
        warning for warning in warning_entries if warning.startswith("faiss_fallback:")
    )
    fallback_detected = any(
        warning.startswith("faiss_fallback:")
        or "faiss" in warning.lower()
        or "missing index" in warning.lower()
        or "channel failed" in warning.lower()
        for warning in warning_entries
    )
    if fallback_detected and not any(
        entry.startswith("faiss_fallback:") for entry in limits
    ):
        limits.append("faiss_fallback:unavailable")
    envelope: AnswerEnvelope = {
        "findings": findings,
        "method": method,
        "limits": limits,
        "answer": "",
        "confidence": confidence,
    }
    return envelope


def _hydrate_findings(
    catalog: DuckDBCatalog,
    ids: Sequence[int],
    scores: Sequence[float],
) -> list[Finding]:
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_exists(conn, _VIEW_CHUNKS):
            return [
                _make_finding(int(chunk_id), float(score))
                for chunk_id, score in zip(ids, scores, strict=False)
            ]
        table = conn.execute(
            'SELECT c.id, c.uri FROM "chunks" AS c '
            "JOIN UNNEST(?) WITH ORDINALITY AS ordering(chunk_id, position)"
            " ON c.id = ordering.chunk_id ORDER BY ordering.position",
            [list(ids)],
        ).fetch_arrow_table()
        findings: list[Finding] = []
        for rank in range(table.num_rows):
            chunk_id = int(table.column(0)[rank].as_py())
            uri = table.column(1)[rank].as_py()
            findings.append(_make_finding(chunk_id, float(scores[rank]), uri))
        return findings


def _make_finding(chunk_id: int, score: float, uri: str | None = None) -> Finding:
    """Create a minimal finding payload for hydrated chunks.

    Returns
    -------
    Finding
        Typed finding dictionary containing chunk identifier and score.
    """
    finding: Finding = {"chunk_id": int(chunk_id), "score": float(score)}
    if uri:
        finding["title"] = str(uri)
    return finding


def _build_method(stage0: Stage0Result, decision: StageDecision) -> MethodInfo:
    """Assemble typed method metadata for the envelope.

    Returns
    -------
    MethodInfo
        Structured method dictionary summarizing Stage-0 and gating decisions.
    """
    gating: MethodGatingInfo = {
        "should_run_secondary_stage": decision.should_run,
        "reason": decision.reason,
    }
    method: MethodInfo = {
        "retrieval": ["hybrid"],
        "stage0": cast("Stage0MethodInfo", dict(stage0.method)),
        "gating": gating,
    }
    if stage0.warnings:
        method["notes"] = list(stage0.warnings)
    return method


def _error_envelope(reason: str) -> AnswerEnvelope:
    """Return a typed error envelope for invalid adapter inputs.

    Returns
    -------
    AnswerEnvelope
        Error envelope carrying the provided reason.
    """
    return cast("AnswerEnvelope", {"error": reason})


__all__ = ["semantic_search"]
