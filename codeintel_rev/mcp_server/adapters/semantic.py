"""Thin semantic search adapter that delegates to the retrieval pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from codeintel_rev.errors import CatalogConsistencyError
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, StructureAnnotations
from codeintel_rev.mcp_server.adapters.async_dependencies import (
    AsyncSearchDependencies,
    build_async_dependencies,
)
from codeintel_rev.mcp_server.method_metadata import MethodInfoComponents
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    ExplanationPayload,
    Finding,
    MethodInfo,
    ScopeIn,
)
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Metadata,
    Stage0Options,
    Stage0Result,
    execute_semantic_stage0,
)

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SNIPPET_PREVIEW_CHARS = 500
_DEFAULT_ASYNC_DEPS = build_async_dependencies()


@dataclass(slots=True, frozen=True)
class SemanticAdapterHooks:
    """Injection points for semantic adapter orchestration."""

    execute_stage0: Callable[[SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]]
    hydrate_findings: Callable[
        [ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None],
        tuple[list[Finding], Exception | None],
    ]


async def semantic_search(
    context: ApplicationContext,
    query: str,
    limit: int = 20,
    *,
    async_deps: AsyncSearchDependencies | None = None,
    hooks: SemanticAdapterHooks | None = None,
) -> AnswerEnvelope:
    """Run semantic search via the shared retrieval pipeline.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings and catalog access.
    query : str
        Search query string.
    limit : int, optional
        Maximum number of findings to return (default 20).
    async_deps : AsyncSearchDependencies | None, optional
        Optional dependency overrides for scope resolution and ``to_thread``.
    hooks : SemanticAdapterHooks | None, optional
        Hook overrides for Stage-0 execution and hydration (primarily for tests).

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings, method metadata, and limits.

    Notes
    -----
    May propagate ``CatalogConsistencyError`` from the underlying synchronous
    search function when DuckDB catalog hydration fails.
    """
    deps = async_deps or _DEFAULT_ASYNC_DEPS
    session_id = deps.session_provider()
    scope = await deps.scope_resolver(context, session_id)
    return await deps.to_thread(
        _semantic_search_sync,
        context,
        query,
        limit,
        scope,
        hooks=hooks,
    )


def _semantic_search_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    scope: ScopeIn | None,
    *,
    hooks: SemanticAdapterHooks | None = None,
) -> AnswerEnvelope:
    """Execute synchronous semantic search and return structured findings.

    This function performs semantic search by executing the Stage-0 retrieval
    pipeline, hydrating results with catalog metadata, annotating hybrid
    contributions, and constructing an AnswerEnvelope response. The function
    handles catalog hydration errors and includes method metadata for
    explainability.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing settings, paths, and catalog access.
        Used to execute retrieval pipeline and access DuckDB catalog for
        result hydration.
    query : str
        Search query string to execute semantic search for. The query is
        passed to the retrieval pipeline for vector similarity search.
    limit : int
        Maximum number of results to return. The limit is passed to the
        retrieval pipeline and used to cap result set size.
    scope : ScopeIn | None
        Optional scope configuration for filtering results by file patterns
        and languages. If provided, scope filters are applied during catalog
        hydration.
    hooks : SemanticAdapterHooks | None, optional
        Optional hook bundle for overriding adapter behavior in tests or
        custom integrations. If None, default adapter behavior is used.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings, method metadata, limits,
        and scope. The envelope includes answer text, query kind, findings list,
        confidence score, and explainability metadata.

    Raises
    ------
    CatalogConsistencyError
        Raised when DuckDB catalog hydration fails. The error includes context
        about DuckDB and vectors directory paths for debugging.

    Notes
    -----
    Synchronous search execution enables thread-safe operation by running
    retrieval and hydration in a separate thread. The function orchestrates
    the complete search pipeline from query execution to result formatting,
    ensuring consistent response structure and error handling.
    """
    active_hooks = hooks or _DEFAULT_HOOKS
    start_time = perf_counter()
    stage0_result, metadata = active_hooks.execute_stage0(
        SemanticStage0Request(
            context=context,
            query=query,
            limit=limit,
            scope=scope,
            options=Stage0Options(),
        )
    )
    findings, hydrate_exc = active_hooks.hydrate_findings(
        context,
        stage0_result.ids,
        stage0_result.scores,
        scope,
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

    method = _compose_method_info(
        stage0_result=stage0_result,
        findings_count=len(findings),
        metadata=metadata,
        start_time=start_time,
        requested_limit=limit,
    )

    extras: AnswerEnvelope = {"method": method}
    if metadata.limits:
        extras["limits"] = list(metadata.limits)
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
    scope: ScopeIn | None = None,
    *,
    catalog: DuckDBCatalog | None = None,
) -> tuple[list[Finding], Exception | None]:
    """Hydrate chunk IDs and scores with catalog metadata to produce findings.

    This function converts chunk IDs and scores into Finding objects by querying
    the DuckDB catalog for chunk metadata, applying scope filters, and extracting
    structure annotations. The function handles catalog errors gracefully by
    returning partial results with exception information.

    Parameters
    ----------
    context : ApplicationContext
        Application context used to open catalog if catalog parameter is None.
        The context provides catalog access for result hydration.
    chunk_ids : Sequence[int]
        Sequence of chunk IDs from semantic search results, ordered by relevance.
        IDs are validated (non-negative) and used to query catalog metadata.
    scores : Sequence[float]
        Sequence of relevance scores corresponding to chunk_ids, ordered by
        relevance (highest first). Scores are included in Finding objects.
    scope : ScopeIn | None, optional
        Optional scope configuration for filtering results by file patterns
        (include_globs, exclude_globs) and languages. If provided, filters
        are applied during catalog querying.
    catalog : DuckDBCatalog | None, optional
        Optional catalog instance to use for hydration. If None, a catalog
        is opened from context. Enables dependency injection for testing.

    Returns
    -------
    tuple[list[Finding], Exception | None]
        Tuple containing:
        - List of Finding objects with hydrated metadata (title, location,
          snippet, score, explanations). Invalid chunk IDs are filtered out.
        - Exception if catalog hydration failed, or None if hydration succeeded.
          Partial results may be returned even if an exception occurred.

    Notes
    -----
    Finding hydration bridges retrieval results (IDs and scores) with rich
    metadata from the catalog (URIs, line numbers, previews, structure
    annotations). The function handles missing chunks gracefully by filtering
    them out, ensuring robust operation even when catalog data is incomplete.
    Scope filtering enables result refinement based on file patterns and
    languages, supporting focused search within specific codebases.
    """

    def _hydrate(active_catalog: DuckDBCatalog) -> tuple[list[Finding], Exception | None]:
        """Inner function that performs catalog hydration with error handling.

        This nested function executes the actual hydration logic, querying the
        catalog for chunk metadata, applying scope filters, extracting structure
        annotations, and constructing Finding objects. The function handles
        catalog errors by returning partial results with exception information.

        Parameters
        ----------
        active_catalog : DuckDBCatalog
            Catalog instance to use for querying chunk metadata. The catalog
            is used to fetch chunk records and structure annotations.

        Returns
        -------
        tuple[list[Finding], Exception | None]
            Tuple containing hydrated findings and optional exception. Returns
            partial results even if an error occurred during hydration.
        """
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
    """Convert structure annotations into explanation payload for findings.

    This function extracts structure metadata from annotations and formats it
    as an ExplanationPayload suitable for inclusion in Finding objects. The
    payload includes matched symbols, AST node kinds, and CST matches that
    explain why a chunk was retrieved.

    Parameters
    ----------
    annotation : StructureAnnotations | None
        Structure annotations for a chunk, containing symbol hits, AST node
        kinds, and CST matches. If None, returns empty explanation payload.

    Returns
    -------
    ExplanationPayload
        Dictionary containing structure explanation metadata:
        - matched_symbols: List of symbol identifiers that matched.
        - ast_kind: Primary AST node kind (first from annotations) or None.
        - cst_hits: List of CST match identifiers or empty list.

    Notes
    -----
    Structure explanations enable users to understand why chunks were retrieved
    by showing which symbols, AST nodes, and CST patterns matched. This
    provides transparency into retrieval decisions and helps users assess
    result relevance. The function handles missing annotations gracefully by
    returning empty explanations.
    """
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
    contribution_map: Mapping[int, list[tuple[str, int, float]]] | None,
    rrf_k: int,
) -> None:
    """Annotate findings with hybrid retrieval contribution information.

    This function updates Finding objects with hybrid contribution metadata,
    showing which channels (semantic, BM25, SPLADE) contributed to each result
    and at what rank. The contribution information is added to the "why" field,
    providing explainability for hybrid search results.

    Parameters
    ----------
    findings : list[Finding]
        List of Finding objects to annotate with hybrid contributions. The
        findings are modified in-place by updating their "why" fields.
    contribution_map : Mapping[int, list[tuple[str, int, float]]] | None
        Optional mapping from chunk IDs to lists of channel contributions.
        Each contribution is a tuple of (channel_name, rank, score). If None
        or empty, no annotations are added.
    rrf_k : int
        RRF (Reciprocal Rank Fusion) k parameter used for hybrid fusion.
        Included in the contribution explanation for transparency.

    Notes
    -----
    Hybrid contribution annotation enables explainability by showing how
    different retrieval channels contributed to final results. The annotation
    replaces or augments the "why" field with detailed channel information,
    helping users understand why documents appear in results. The function
    handles missing contributions gracefully by skipping findings without
    contribution data.
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


def _compose_method_info(
    stage0_result: Stage0Result,
    findings_count: int,
    metadata: Stage0Metadata,
    start_time: float,
    requested_limit: int,
) -> MethodInfo:
    """Compose retrieval method metadata for the semantic adapter.

    Parameters
    ----------
    stage0_result : Stage0Result
        Stage-0 retrieval result containing channels and method metadata.
    findings_count : int
        Number of findings produced from the retrieval results.
    metadata : Stage0Metadata
        Stage-0 metadata containing effective limit and other execution details.
    start_time : float
        Start time from perf_counter() for computing elapsed time.
    requested_limit : int
        Original limit requested by the user, used for coverage reporting.

    Returns
    -------
    MethodInfo
        Method metadata dictionary containing retrieval channels, coverage string,
        and stage0 method details. The coverage string includes findings count,
        effective limit, elapsed time, and requested limit if different.
    """
    channels = list(stage0_result.channels or ["semantic"])
    elapsed_ms = int((perf_counter() - start_time) * 1000)
    coverage = f"{findings_count}/{metadata.effective_limit} results in {elapsed_ms}ms"
    if requested_limit != metadata.effective_limit:
        coverage = f"{coverage} (requested {requested_limit})"

    return MethodInfoComponents(
        retrieval_channels=channels,
        coverage=coverage,
        stage0=stage0_result.method,
    ).as_method_info()


def build_semantic_adapter_hooks(
    *,
    execute_stage0: Callable[
        [SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]
    ] = execute_semantic_stage0,
    hydrate_findings: Callable[
        [ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None],
        tuple[list[Finding], Exception | None],
    ] = _hydrate_findings,
) -> SemanticAdapterHooks:
    """Return hooks for overriding Stage-0 execution or hydration.

    Parameters
    ----------
    execute_stage0 : Callable[[SemanticStage0Request], tuple[Stage0Result, Stage0Metadata]], optional
        Optional function to override Stage-0 execution. Defaults to execute_semantic_stage0.
        Used for dependency injection in tests.
    hydrate_findings : Callable[[ApplicationContext, Sequence[int], Sequence[float], ScopeIn | None], tuple[list[Finding], Exception | None]], optional
        Optional function to override finding hydration. Defaults to _hydrate_findings.
        Used for dependency injection in tests.

    Returns
    -------
    SemanticAdapterHooks
        Hooks object with the provided overrides (falling back to production defaults).
    """
    return SemanticAdapterHooks(
        execute_stage0=execute_stage0,
        hydrate_findings=hydrate_findings,
    )


_DEFAULT_HOOKS = build_semantic_adapter_hooks()


__all__ = ["semantic_search"]
