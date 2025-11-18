"""Thin semantic search adapter that delegates to the retrieval pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.errors import CatalogConsistencyError
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ExplanationPayload, Finding, ScopeIn
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Options,
    execute_semantic_stage0,
)

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SNIPPET_PREVIEW_CHARS = 500


async def semantic_search(
    context: ApplicationContext,
    query: str,
    limit: int = 20,
) -> AnswerEnvelope:
    """Run semantic search via the shared retrieval pipeline.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings, method metadata, and limits.
    """
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    return await asyncio.to_thread(_semantic_search_sync, context, query, limit, scope)


def _semantic_search_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    scope: ScopeIn | None,
) -> AnswerEnvelope:
    start_time = perf_counter()
    stage0_result, metadata = execute_semantic_stage0(
        SemanticStage0Request(
            context=context,
            query=query,
            limit=limit,
            scope=scope,
            options=Stage0Options(),
        )
    )
    findings, hydrate_exc = _hydrate_findings(
        context,
        stage0_result.ids,
        stage0_result.scores,
        scope=scope,
    )
    if hydrate_exc is not None:
        message = "DuckDB hydration failed"
        raise CatalogConsistencyError(
            message,
            context={
                "duckdb_path": str(context.paths.duckdb_path),
                "vectors_dir": str(context.paths.vectors_dir),
            },
        ) from hydrate_exc

    _annotate_hybrid_contributions(
        findings,
        stage0_result.contributions,
        context.settings.index.rrf_k,
    )

    method = {
        "retrieval": stage0_result.channels or ["semantic"],
        "coverage": f"{len(findings)}/{metadata.effective_limit} results in "
        f"{int((perf_counter() - start_time) * 1000)}ms",
        "stage0": stage0_result.method or {},
    }

    extras: AnswerEnvelope = {"method": method}
    if metadata.limits:
        extras["limits"] = metadata.limits
    if scope:
        extras["scope"] = scope

    return {
        **extras,
        "answer": f"Found {len(findings)} semantic results for: {query}",
        "query_kind": "semantic",
        "findings": findings,
        "confidence": 0.85 if findings else 0.0,
    }


def _hydrate_findings(
    context: ApplicationContext,
    chunk_ids: Sequence[int],
    scores: Sequence[float],
    *,
    scope: ScopeIn | None = None,
    catalog: DuckDBCatalog | None = None,
) -> tuple[list[Finding], Exception | None]:
    def _hydrate(active_catalog: DuckDBCatalog) -> tuple[list[Finding], Exception | None]:
        findings: list[Finding] = []
        try:
            valid_ids = [int(chunk_id) for chunk_id in chunk_ids if chunk_id >= 0]
            if not valid_ids:
                return [], None

            include_globs = scope.get("include_globs") if scope else None
            exclude_globs = scope.get("exclude_globs") if scope else None
            languages = scope.get("languages") if scope else None
            has_filters = bool(include_globs or exclude_globs or languages)

            if has_filters:
                records = active_catalog.query_by_filters(
                    valid_ids,
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                    languages=languages,
                )
            else:
                records = active_catalog.query_by_ids(valid_ids)
            annotations = active_catalog.get_structure_annotations(valid_ids)
            chunk_by_id = {int(record["id"]): record for record in records if "id" in record}

            for chunk_id, score in zip(chunk_ids, scores, strict=True):
                if chunk_id < 0:
                    continue
                chunk = chunk_by_id.get(int(chunk_id))
                if not chunk:
                    continue

                finding: Finding = {
                    "type": "usage",
                    "title": f"{Path(chunk['uri']).name} (score: {score:.3f})",
                    "location": {
                        "uri": chunk["uri"],
                        "start_line": chunk["start_line"],
                        "start_column": 0,
                        "end_line": chunk["end_line"],
                        "end_column": 0,
                    },
                    "snippet": chunk["preview"][:SNIPPET_PREVIEW_CHARS],
                    "score": float(score),
                    "why": f"Semantic similarity: {score:.3f}",
                    "chunk_id": int(chunk_id),
                }
                finding["explanations"] = _structure_explanations(annotations.get(int(chunk_id)))
                findings.append(finding)
        except (RuntimeError, OSError) as exc:
            return findings, exc
        return findings, None

    if catalog is not None:
        return _hydrate(catalog)
    with context.open_catalog() as owned_catalog:
        return _hydrate(owned_catalog)


def _structure_explanations(annotation: StructureAnnotations | None) -> ExplanationPayload:
    if annotation is None:
        return {
            "matched_symbols": [],
            "ast_kind": None,
            "cst_hits": [],
        }
    matched = [str(sym) for sym in annotation.symbol_hits]
    ast_kind = annotation.ast_node_kinds[0] if annotation.ast_node_kinds else None
    cst_hits = [str(hit) for hit in annotation.cst_matches] if annotation.cst_matches else []
    return {
        "matched_symbols": matched,
        "ast_kind": ast_kind,
        "cst_hits": cst_hits,
    }


def _annotate_hybrid_contributions(
    findings: list[Finding],
    contribution_map: dict[int, list[tuple[str, int, float]]] | None,
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


__all__ = ["semantic_search"]
