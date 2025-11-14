"""Deep-Research compatible search/fetch orchestration helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

import numpy as np

from codeintel_rev.eval.pool_writer import write_pool
from codeintel_rev.io.faiss_manager import SearchRuntimeOverrides
from codeintel_rev.metrics.registry import (
    MCP_FETCH_LATENCY_SECONDS,
    MCP_SEARCH_ANN_LATENCY_MS,
    MCP_SEARCH_HYDRATION_LATENCY_MS,
    MCP_SEARCH_LATENCY_SECONDS,
    MCP_SEARCH_POSTFILTER_DENSITY,
    MCP_SEARCH_RERANK_LATENCY_MS,
)
from codeintel_rev.observability.otel import record_span_event
from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
from codeintel_rev.retrieval.types import SearchPoolRow
from codeintel_rev.telemetry.decorators import span_context
from codeintel_rev.typing import NDArrayF32, NDArrayI64
from kgfoundry_common.errors import EmbeddingError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.io.duckdb_catalog import StructureAnnotations
    from codeintel_rev.mcp_server.schemas import SearchFilterPayload
    from codeintel_rev.observability.timeline import Timeline

type EmbeddingVector = Sequence[float] | NDArrayF32

LOGGER = get_logger(__name__)


class EmbeddingClient(Protocol):
    """Protocol describing the minimal embedder surface needed for search."""

    def embed_single(self, text: str) -> EmbeddingVector:
        """Return a single embedding vector for ``text``."""
        ...


class IndexConfigLike(Protocol):
    """PEP 544 view of the index configuration needed by MCP search."""

    @property
    def vec_dim(self) -> int:
        """Return the vector dimension for embeddings.

        Returns
        -------
        int
            The dimension of embedding vectors used by the FAISS index.
            This value must match the dimension of vectors produced by
            the embedding service and stored in the index.
        """
        ...

    @property
    def faiss_nprobe(self) -> int:
        """Return the FAISS nprobe parameter for approximate search.

        Returns
        -------
        int
            The number of inverted list clusters to probe during approximate
            nearest neighbor search. Higher values improve recall at the cost
            of latency. Used to configure FAISS index search behavior.
        """
        ...


class LimitsConfigLike(Protocol):
    """PEP 544 view of server limit configuration."""

    @property
    def max_results(self) -> int:
        """Return the maximum number of results allowed per search request.

        Returns
        -------
        int
            The maximum number of results that can be returned from a single
            search request. Used to enforce resource limits and prevent excessive
            result sets. Search requests requesting more than this value will be
            capped at this limit.
        """
        ...

    @property
    def semantic_overfetch_multiplier(self) -> int:
        """Return the multiplier for semantic search overfetch when filters are active.

        Returns
        -------
        int
            Multiplier applied to the requested top_k when post-filtering is
            enabled (path filters, language filters, or symbol filters). Used
            to fetch more candidates than requested to account for results that
            will be filtered out. For example, if top_k=10 and multiplier=3,
            the search will fetch 30 candidates to ensure enough results survive
            post-filtering.
        """
        ...


class SearchSettings(Protocol):
    """Protocol for the subset of :class:`~codeintel_rev.config.settings.Settings`."""

    @property
    def index(self) -> IndexConfigLike:
        """Return immutable index configuration."""
        ...

    @property
    def limits(self) -> LimitsConfigLike:
        """Return immutable server limit configuration."""
        ...


class CatalogLike(Protocol):
    """DuckDB catalog surface used by the MCP tools."""

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        """Return chunk rows for the provided ids."""
        ...

    def query_by_filters(
        self,
        ids: Sequence[int],
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Return filtered chunk rows for the provided ids."""
        ...

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, StructureAnnotations]:
        """Return structural overlays for ``ids`` when available."""
        ...


class VectorIndex(Protocol):
    """FAISS manager surface consumed by MCP search."""

    vec_dim: int
    faiss_family: str | None
    refine_k_factor: float

    def get_runtime_tuning(self) -> Mapping[str, object]:
        """Return runtime FAISS tuning metadata."""
        ...

    def search(
        self,
        query: NDArrayF32,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: SearchRuntimeOverrides | None = None,
        catalog: object | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Perform ANN search and return (distances, ids)."""
        ...


@dataclass(slots=True, frozen=True)
class SearchFilters:
    """Normalized filter payload for the MCP search tool."""

    languages: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Sequence[str]] | SearchFilterPayload | None,
    ) -> SearchFilters:
        """Normalize the incoming JSON payload into immutable tuples.

        This class method converts a JSON payload dictionary (from MCP tool arguments)
        into a SearchFilters instance with immutable tuple-backed sequences. The method
        handles missing keys gracefully, normalizes string lists, and validates filter
        values. Used to convert MCP search filter payloads into typed filter objects.

        Parameters
        ----------
        payload : Mapping[str, Sequence[str]] | SearchFilterPayload | None
            Optional JSON payload dictionary containing filter keys: "lang" (languages),
            "include" (include paths), "exclude" (exclude paths), "symbols" (symbol
            filters). Values are sequences of strings that are normalized and converted
            to tuples. When None or empty, returns a SearchFilters instance with empty
            tuples (no filters). Can accept either Mapping[str, Sequence[str]] or
            SearchFilterPayload TypedDict format.

        Returns
        -------
        SearchFilters
            SearchFilters instance with normalized filter tuples. All filter fields
            (languages, include, exclude, symbols) are immutable tuples, even when
            the payload is empty or missing keys.
        """
        if not payload:
            return cls()
        return cls(
            languages=tuple(_normalize_str_list(payload.get("lang"))),
            include=tuple(_normalize_str_list(payload.get("include"))),
            exclude=tuple(_normalize_str_list(payload.get("exclude"))),
            symbols=tuple(_normalize_str_list(payload.get("symbols"))),
        )

    @property
    def has_path_filters(self) -> bool:
        """Return ``True`` when include/exclude filters are present.

        Returns
        -------
        bool
            ``True`` when include/exclude filters were provided.
        """
        return bool(self.include or self.exclude)

    @property
    def has_language_filters(self) -> bool:
        """Return ``True`` when language filters are present.

        Returns
        -------
        bool
            ``True`` when the filter payload includes languages.
        """
        return bool(self.languages)

    def describe(self) -> dict[str, object]:
        """Return a JSON-safe description for structured logging.

        Returns
        -------
        dict[str, object]
            Mapping containing canonical filter fields.
        """
        return {
            "lang": list(self.languages),
            "include": list(self.include),
            "exclude": list(self.exclude),
            "symbols": list(self.symbols),
        }


@dataclass(slots=True, frozen=True)
class SearchRequest:
    """Search invocation parameters."""

    query: str
    top_k: int
    rerank: bool
    filters: SearchFilters


@dataclass(slots=True, frozen=True)
class SearchResult:
    """Single search result entry."""

    chunk_id: int
    title: str
    url: str
    snippet: str
    score: float
    source: str
    metadata: dict[str, object]


@dataclass(slots=True, frozen=True)
class SearchResponse:
    """Structured search response returned to MCP adapters."""

    query_echo: str
    top_k: int
    results: list[SearchResult]
    limits: list[str]


@dataclass(slots=True, frozen=True)
class HydrationPayload:
    """Bundle of hydrated rows and structural annotations."""

    rows: Mapping[int, dict[str, object]]
    annotations: Mapping[int, StructureAnnotations]


@dataclass(slots=True)
class _StageDurations:
    """Per-stage latencies captured during a search run."""

    ann: float = 0.0
    hydrate: float = 0.0
    rerank: float = 0.0


@dataclass(slots=True, frozen=True)
class SearchDependencies:
    """Dependency bundle consumed by :func:`run_search`."""

    faiss: VectorIndex
    embedder: EmbeddingClient
    catalog: CatalogLike
    settings: SearchSettings
    session_id: str | None
    run_id: str | None
    limits: Sequence[str]
    pool_dir: Path | None
    timeline: Timeline | None


@dataclass(slots=True, frozen=True)
class FetchRequest:
    """Fetch invocation parameters."""

    object_ids: tuple[int, ...]
    max_tokens: int


@dataclass(slots=True, frozen=True)
class FetchObjectResult:
    """Single hydrated chunk."""

    chunk_id: int
    title: str
    url: str
    content: str
    metadata: dict[str, object]


@dataclass(slots=True, frozen=True)
class FetchResponse:
    """Structured fetch response used by MCP adapters."""

    objects: list[FetchObjectResult]


@dataclass(slots=True, frozen=True)
class FetchDependencies:
    """Dependency bundle for :func:`run_fetch`."""

    catalog: CatalogLike
    settings: SearchSettings
    timeline: Timeline | None


def run_search(*, request: SearchRequest, deps: SearchDependencies) -> SearchResponse:
    """Execute FAISS search → DuckDB hydration and return MCP-ready results.

    This function orchestrates the complete search workflow: embeds the query text,
    executes FAISS approximate nearest neighbor search, optionally reranks candidates
    with exact similarity, hydrates chunk metadata from DuckDB, applies post-search
    filters, and builds ranked results. The function records metrics (latency, postfilter
    density) and writes pool rows for trace analysis.

    Parameters
    ----------
    request : SearchRequest
        Search request containing query text, top_k (number of results), rerank flag,
        and optional filters (languages, paths, symbols). Used to configure search
        behavior and result filtering.
    deps : SearchDependencies
        Search dependencies providing FAISS manager, embedding client, DuckDB catalog,
        settings, timeline, and pool directory. Used to execute search operations and
        hydrate results. The dependencies must be initialized and ready for use.

    Returns
    -------
    SearchResponse
        Dataclass containing search hits and diagnostic metadata. Includes query_echo
        (original query), top_k (requested results), results (ranked SearchResult objects
        with chunk metadata and scores), and limits (resource limits applied during search).
    """
    start = perf_counter()
    search_attrs = _build_search_attrs(request, deps)
    faiss_k = _compute_fanout(request.top_k, request.filters, deps.settings.limits)
    search_attrs[Attrs.FAISS_TOP_K] = faiss_k
    durations = _StageDurations()
    with span_context(
        "retrieval.search",
        kind="internal",
        attrs=search_attrs,
        emit_checkpoint=True,
    ):
        record_span_event(
            "retrieval.search.accepted",
            query=request.query,
            top_k=request.top_k,
            rerank=request.rerank,
        )
        query_vector = _embed_with_metrics(request, deps)
        distances, identifiers, durations.ann = _run_ann_search(
            request,
            deps,
            query_vector,
            faiss_k,
        )
        ranked_ids = _flatten_ids(identifiers)
        hydration_bundle, durations.hydrate = _hydrate_with_metrics(
            deps,
            ranked_ids,
            request,
        )
        results, repair_stats, durations.rerank = _rerank_with_metrics(
            ranked_ids=ranked_ids,
            scores=_flatten_scores(distances),
            hydration=hydration_bundle,
            request=request,
            source_label=f"faiss_{deps.faiss.faiss_family or 'auto'}",
        )
        limits = _compose_limits(deps.limits, results, repair_stats)
        MCP_SEARCH_ANN_LATENCY_MS.observe(max(durations.ann * 1000.0, 0.0))
        MCP_SEARCH_HYDRATION_LATENCY_MS.observe(max(durations.hydrate * 1000.0, 0.0))
        MCP_SEARCH_RERANK_LATENCY_MS.observe(max(durations.rerank * 1000.0, 0.0))
        total_duration = max(perf_counter() - start, 0.0)
        MCP_SEARCH_LATENCY_SECONDS.observe(total_duration)
        _record_postfilter_density(len(results), repair_stats.inspected)
        _write_pool_rows(results, deps, hydration_bundle.annotations)
        _log_search_completion(request, deps, len(results), faiss_k)
        record_span_event(
            "retrieval.search.complete",
            results=len(results),
            duration_s=total_duration,
            faiss_k=faiss_k,
        )
        return SearchResponse(
            query_echo=request.query,
            top_k=request.top_k,
            results=results,
            limits=limits,
        )


def run_fetch(*, request: FetchRequest, deps: FetchDependencies) -> FetchResponse:
    """Hydrate chunk content and metadata for the MCP fetch tool.

    This function retrieves full chunk content and metadata for a list of chunk IDs
    from the DuckDB catalog. The function queries the catalog, builds FetchObjectResult
    objects with content and metadata, applies max_tokens limits, and records metrics
    (latency, token counts). Used to hydrate chunk IDs returned from search operations.

    Parameters
    ----------
    request : FetchRequest
        Fetch request containing object_ids (list of chunk IDs to hydrate) and
        max_tokens (optional token limit). Used to query the catalog and limit response
        size. Empty object_ids return an empty response immediately.
    deps : FetchDependencies
        Fetch dependencies providing DuckDB catalog, settings, and timeline. Used to
        query chunk metadata and record observability events. The catalog must be
        initialized and ready for queries.

    Returns
    -------
    FetchResponse
        Dataclass containing hydrated chunk objects. Includes a list of FetchObjectResult
        objects with chunk_id, title, url, content, and metadata fields. Chunks are
        returned in the order specified by request.object_ids, with missing chunks
        omitted. Content is truncated to max_tokens when specified.
    """
    start = perf_counter()
    attrs = {
        Attrs.STAGE: "hydrate.fetch",
        Attrs.DUCKDB_ROWS: len(request.object_ids),
    }
    with span_context("retrieval.fetch", kind="internal", attrs=attrs):
        if not request.object_ids:
            return FetchResponse(objects=[])
        rows = deps.catalog.query_by_ids(request.object_ids)
        by_id: dict[int, dict[str, object]] = {}
        for row in rows:
            identifier = row.get("id")
            if isinstance(identifier, int):
                by_id[identifier] = row
        objects: list[FetchObjectResult] = []
        for chunk_id in request.object_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            objects.append(
                FetchObjectResult(
                    chunk_id=chunk_id,
                    title=_build_title(row),
                    url=_build_url(row),
                    content=_truncate_content(str(row.get("content") or ""), request.max_tokens),
                    metadata=_build_fetch_metadata(row),
                )
            )
        duration = max(perf_counter() - start, 0.0)
        MCP_FETCH_LATENCY_SECONDS.observe(duration)
        record_span_event("retrieval.fetch.complete", duration_s=duration, hydrated=len(objects))
        return FetchResponse(objects=objects)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _normalize_str_list(values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _build_search_attrs(request: SearchRequest, deps: SearchDependencies) -> dict[str, object]:
    """Return the base telemetry attributes for ``run_search`` spans.

    Parameters
    ----------
    request : SearchRequest
        Incoming search request describing query text and filters.
    deps : SearchDependencies
        Dependency bundle carrying session metadata for telemetry.

    Returns
    -------
    dict[str, object]
        Structured attributes used to initialize the retrieval span.
    """
    attrs: dict[str, object] = {
        Attrs.RETRIEVAL_TOP_K: request.top_k,
        Attrs.QUERY_TEXT: request.query,
        Attrs.QUERY_LEN: len(request.query),
    }
    if deps.session_id:
        attrs[Attrs.MCP_SESSION_ID] = deps.session_id
    if deps.run_id:
        attrs[Attrs.MCP_RUN_ID] = deps.run_id
    if request.filters.languages:
        attrs["retrieval.languages"] = to_label_str(request.filters.languages)
    if request.filters.include or request.filters.exclude:
        attrs["retrieval.paths"] = to_label_str(
            {
                "include": request.filters.include,
                "exclude": request.filters.exclude,
            }
        )
    return attrs


def _embed_with_metrics(request: SearchRequest, deps: SearchDependencies) -> NDArrayF32:
    """Embed the query text and emit timing telemetry.

    Parameters
    ----------
    request : SearchRequest
        Search request providing query text to embed.
    deps : SearchDependencies
        Dependency bundle with configured embedder and settings.

    Returns
    -------
    NDArrayF32
        Normalized query embedding reshaped to ``(1, vec_dim)``.
    """
    embed_start = perf_counter()
    with span_context(
        "retrieval.embed",
        kind="internal",
        attrs={
            Attrs.STAGE: "embed",
            Attrs.QUERY_LEN: len(request.query),
        },
    ):
        vector = _embed_query(deps.embedder, request.query, deps.settings.index.vec_dim)
    embed_elapsed = perf_counter() - embed_start
    record_span_event("retrieval.embed.complete", duration_ms=embed_elapsed * 1000.0)
    return vector


def _run_ann_search(
    request: SearchRequest,
    deps: SearchDependencies,
    query_vector: NDArrayF32,
    faiss_k: int,
) -> tuple[NDArrayF32, NDArrayI64, float]:
    """Execute FAISS search and report elapsed time.

    Parameters
    ----------
    request : SearchRequest
        Search request used to determine rerank behavior.
    deps : SearchDependencies
        Dependency bundle supplying the FAISS index and settings.
    query_vector : NDArrayF32
        Embedded query vector produced by the embedder.
    faiss_k : int
        Number of neighbors to retrieve from the FAISS index.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64, float]
        Tuple containing cosine distances, identifiers, and elapsed seconds.
    """
    ann_start = perf_counter()
    with span_context(
        "retrieval.ann",
        kind="internal",
        attrs={
            Attrs.STAGE: "gather_channels",
            Attrs.FAISS_TOP_K: faiss_k,
            Attrs.FAISS_NPROBE: deps.settings.index.faiss_nprobe,
        },
    ):
        distances, identifiers = deps.faiss.search(
            query_vector,
            k=faiss_k,
            nprobe=deps.settings.index.faiss_nprobe,
            runtime=_build_runtime_overrides(rerank=request.rerank),
            catalog=deps.catalog if request.rerank else None,
        )
    return distances, identifiers, perf_counter() - ann_start


def _hydrate_with_metrics(
    deps: SearchDependencies,
    ranked_ids: Sequence[int],
    request: SearchRequest,
) -> tuple[HydrationPayload, float]:
    """Hydrate chunk metadata and annotations with telemetry.

    Parameters
    ----------
    deps : SearchDependencies
        Dependency bundle providing the catalog handle.
    ranked_ids : Sequence[int]
        Ordered chunk identifiers returned from FAISS.
    request : SearchRequest
        Search request whose filters guide hydration.

    Returns
    -------
    tuple[HydrationPayload, float]
        Hydration payload (rows and annotations) with elapsed seconds.
    """
    hyd_start = perf_counter()
    with span_context(
        "retrieval.hydrate",
        kind="internal",
        attrs={
            Attrs.STAGE: "hydrate",
            Attrs.RETRIEVAL_TOP_K: request.top_k,
        },
    ):
        chunk_rows = _hydrate_chunks(
            deps.catalog,
            ranked_ids,
            request.filters,
        )
        annotations = cast(
            "Mapping[int, StructureAnnotations]",
            deps.catalog.get_structure_annotations(tuple(chunk_rows.keys()))
            if chunk_rows
            else {},
        )
    elapsed = perf_counter() - hyd_start
    return HydrationPayload(rows=chunk_rows, annotations=annotations), elapsed


def _rerank_with_metrics(
    *,
    ranked_ids: Sequence[int],
    scores: Sequence[float],
    hydration: HydrationPayload,
    request: SearchRequest,
    source_label: str,
) -> tuple[list[SearchResult], _RepairStats, float]:
    """Apply post-filtering/rerank logic and emit telemetry.

    Parameters
    ----------
    ranked_ids : Sequence[int]
        Ranked chunk identifiers after FAISS search.
    scores : Sequence[float]
        Corresponding similarity scores for ``ranked_ids``.
    hydration : HydrationPayload
        Hydrated chunk rows and annotations.
    request : SearchRequest
        Original request controlling rerank toggle and filters.
    source_label : str
        Label describing the source of the result scores.

    Returns
    -------
    tuple[list[SearchResult], _RepairStats, float]
        Tuple of validated results, repair stats, and elapsed seconds.
    """
    rerank_start = perf_counter()
    with span_context(
        "retrieval.rerank",
        kind="internal",
        attrs={
            Attrs.STAGE: "rerank",
            "rerank.enabled": str(request.rerank),
        },
    ):
        results, repair_stats = post_search_validate_and_fill(
            _build_results(
                ranked_ids,
                scores,
                hydration=hydration,
                request=request,
                source_label=source_label,
            ),
            hydration=hydration,
        )
    return results, repair_stats, perf_counter() - rerank_start


def _compose_limits(
    base_limits: Sequence[str],
    results: Sequence[SearchResult],
    repair_stats: _RepairStats,
) -> list[str]:
    """Augment limit annotations with validator statistics.

    Parameters
    ----------
    base_limits : Sequence[str]
        Existing limits derived from dependency configuration.
    results : Sequence[SearchResult]
        Final search results returned to callers.
    repair_stats : _RepairStats
        Validator statistics describing inspected/dropped rows.

    Returns
    -------
    list[str]
        Composite list of limit annotations augmented with validators.
    """
    limits = list(base_limits)
    limits.extend(
        [
            f"postfilter_density={len(results) / max(repair_stats.inspected, 1):.2f}",
            f"dropped={repair_stats.dropped}",
            f"repaired={repair_stats.repaired}",
        ]
    )
    return limits


def _embed_query(embedder: EmbeddingClient, query: str, vec_dim: int) -> NDArrayF32:
    with span_context(
        "retrieval.embed.query",
        kind="internal",
        attrs={
            Attrs.STAGE: "embed",
            Attrs.QUERY_LEN: len(query),
        },
    ):
        try:
            vector = embedder.embed_single(query)
        except (RuntimeError, ValueError) as exc:  # pragma: no cover - network errors
            msg = "Embedding service unavailable"
            raise EmbeddingError(msg, cause=exc) from exc
        array = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        if array.shape[1] != vec_dim:
            msg = f"Embedding dimension mismatch: expected {vec_dim}, got {array.shape[1]}"
            raise EmbeddingError(msg)
        record_span_event("retrieval.embed.query.complete", dim=array.shape[1])
        return array


def _compute_fanout(top_k: int, filters: SearchFilters, limits: LimitsConfigLike) -> int:
    multiplier = (
        limits.semantic_overfetch_multiplier
        if (filters.has_path_filters or filters.has_language_filters or filters.symbols)
        else 1
    )
    return max(top_k, min(limits.max_results, top_k * max(1, multiplier)))


def _build_runtime_overrides(*, rerank: bool) -> SearchRuntimeOverrides | None:
    """Return FAISS runtime overrides derived from the rerank flag.

    This helper function constructs FAISS runtime overrides based on the rerank
    configuration. When rerank is disabled, returns overrides that set k_factor=1.0
    to disable candidate expansion (since exact reranking won't be performed). When
    rerank is enabled, returns None to use default overrides (which enable expansion).

    Parameters
    ----------
    rerank : bool
        Whether exact reranking is enabled. When False, returns overrides with
        k_factor=1.0 to disable candidate expansion. When True, returns None
        to use default overrides that enable expansion for reranking.

    Returns
    -------
    SearchRuntimeOverrides | None
        Runtime overrides with k_factor=1.0 when rerank is False (disables expansion),
        otherwise None (uses default overrides that enable expansion for reranking).
        The overrides are applied to FAISS search to control candidate retrieval.
    """
    if rerank:
        return None
    return SearchRuntimeOverrides(k_factor=1.0)


def _flatten_ids(identifiers: NDArrayI64) -> list[int]:
    if identifiers.size == 0:
        return []
    return [int(chunk_id) for chunk_id in identifiers[0].tolist() if chunk_id >= 0]


def _flatten_scores(distances: NDArrayF32) -> list[float]:
    if distances.size == 0:
        return []
    return [float(score) for score in distances[0].tolist()]


def _hydrate_chunks(
    catalog: CatalogLike,
    chunk_ids: Sequence[int],
    filters: SearchFilters,
) -> dict[int, dict[str, object]]:
    if not chunk_ids:
        return {}
    if filters.has_path_filters or filters.has_language_filters:
        rows = catalog.query_by_filters(
            chunk_ids,
            include_globs=list(filters.include) or None,
            exclude_globs=list(filters.exclude) or None,
            languages=list(filters.languages) or None,
        )
    else:
        rows = catalog.query_by_ids(chunk_ids)
    chunk_map: dict[int, dict[str, object]] = {}
    for row in rows:
        identifier = row.get("id")
        if isinstance(identifier, int):
            chunk_map[identifier] = row
    return chunk_map


def _build_results(
    ranked_ids: Sequence[int],
    scores: Sequence[float],
    *,
    hydration: HydrationPayload,
    request: SearchRequest,
    source_label: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for chunk_id, score in zip(ranked_ids, scores, strict=False):
        row = hydration.rows.get(chunk_id)
        if row is None:
            continue
        if request.filters.symbols and not _matches_symbols(row, request.filters.symbols):
            continue
        meta = _build_metadata(row, hydration.annotations.get(chunk_id), request, score)
        results.append(
            SearchResult(
                chunk_id=chunk_id,
                title=_build_title(row),
                url=_build_url(row),
                snippet=_build_snippet(row),
                score=float(score),
                source=source_label,
                metadata=meta,
            )
        )
        if len(results) >= request.top_k:
            break
    return results


def _matches_symbols(row: Mapping[str, object], symbols: Sequence[str]) -> bool:
    chunk_symbols = set(_string_sequence(row.get("symbols")))
    if not chunk_symbols:
        return False
    return any(symbol in chunk_symbols for symbol in symbols)


def _build_metadata(
    row: Mapping[str, object],
    annotation: StructureAnnotations | None,
    request: SearchRequest,
    score: float,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "uri": str(row.get("uri")),
        "start_line": _coerce_int(row.get("start_line")),
        "end_line": _coerce_int(row.get("end_line")),
        "start_byte": _coerce_int(row.get("start_byte")),
        "end_byte": _coerce_int(row.get("end_byte")),
        "lang": str(row.get("lang") or ""),
        "symbols": _string_sequence(row.get("symbols")),
    }
    explain = {
        "hit_reason": _build_hit_reasons(request, metadata, score),
        "scip": bool(getattr(annotation, "symbol_hits", ())),
        "ast": bool(getattr(annotation, "ast_node_kinds", ())),
        "cst": bool(getattr(annotation, "cst_matches", ())),
    }
    metadata["explain"] = explain
    return metadata


def _build_hit_reasons(
    request: SearchRequest,
    metadata: Mapping[str, object],
    score: float,
) -> list[str]:
    reasons = ["embedding:cosine"]
    if request.filters.languages:
        reasons.append(f"filter:lang={'/'.join(request.filters.languages)}")
    if request.filters.include:
        reasons.append("filter:path:include")
    if request.filters.exclude:
        reasons.append("filter:path:exclude")
    if request.filters.symbols:
        chunk_symbols = set(_string_sequence(metadata.get("symbols")))
        matched = sorted(chunk_symbols & set(request.filters.symbols))
        reasons.extend(f"symbol:name:{symbol}" for symbol in matched)
    if request.rerank:
        reasons.append("rerank:exact")
    reasons.append(f"score:{score:.3f}")
    return reasons


def _build_title(row: Mapping[str, object]) -> str:
    uri = str(row.get("uri") or "")
    start_line = _coerce_int(row.get("start_line")) + 1
    end_line = _coerce_int(row.get("end_line")) + 1
    return f"{uri}: lines {start_line}-{max(start_line, end_line)}"


def _build_url(row: Mapping[str, object]) -> str:
    uri = str(row.get("uri") or "")
    start_line = _coerce_int(row.get("start_line")) + 1
    end_line = _coerce_int(row.get("end_line")) + 1
    return f"repo://{uri}#L{start_line}-L{max(start_line, end_line)}"


def _build_snippet(row: Mapping[str, object]) -> str:
    preview = row.get("preview")
    if preview:
        return str(preview)[:400]
    content = str(row.get("content") or "")
    return content[:400]


def _truncate_content(content: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(content) <= max_chars:
        return content
    truncated = content[: max(0, max_chars - 1)].rsplit("\n", 1)[0]
    return truncated + "\n…"


def _build_fetch_metadata(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "uri": str(row.get("uri")),
        "start_line": _coerce_int(row.get("start_line")),
        "end_line": _coerce_int(row.get("end_line")),
        "start_byte": _coerce_int(row.get("start_byte")),
        "end_byte": _coerce_int(row.get("end_byte")),
        "lang": str(row.get("lang") or ""),
    }


def _write_pool_rows(
    results: Sequence[SearchResult],
    deps: SearchDependencies,
    annotations: Mapping[int, StructureAnnotations],
) -> None:
    if not results or deps.pool_dir is None:
        return
    try:
        deps.pool_dir.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - filesystem tolerance
        return
    query_id = deps.run_id or uuid4().hex
    rows: list[SearchPoolRow] = []
    for rank, result in enumerate(results, start=1):
        annotation = annotations.get(result.chunk_id)
        symbol_hits = annotation.symbol_hits if annotation else ()
        ast_node_kinds = annotation.ast_node_kinds if annotation else ()
        cst_matches = annotation.cst_matches if annotation else ()
        meta = {
            "uri": str(result.metadata.get("uri")),
            "symbol_hits": list(symbol_hits),
            "ast_node_kinds": list(ast_node_kinds),
            "cst_matches": list(cst_matches),
            "score": result.score,
        }
        rows.append(
            SearchPoolRow(
                query_id=query_id,
                channel="faiss",
                rank=rank,
                id=result.chunk_id,
                score=result.score,
                meta=meta,
            )
        )
    destination = deps.pool_dir / f"{query_id}.parquet"
    try:
        write_pool(rows, destination)
    except RuntimeError:  # pragma: no cover - optional dependency
        LOGGER.debug("pool_writer.pyarrow_missing", extra={"path": str(destination)})


def _record_postfilter_density(retained: int, initial: int) -> None:
    if initial <= 0:
        return
    ratio = retained / float(initial)
    MCP_SEARCH_POSTFILTER_DENSITY.observe(ratio)


def _log_search_completion(
    request: SearchRequest, deps: SearchDependencies, returned: int, fanout: int
) -> None:
    LOGGER.info(
        "mcp.search.complete",
        extra={
            "query_chars": len(request.query),
            "returned": returned,
            "top_k": request.top_k,
            "fanout": fanout,
            "filters": request.filters.describe(),
            "rerank": request.rerank,
            "index_family": deps.faiss.faiss_family or "auto",
            "faiss_runtime": dict(deps.faiss.get_runtime_tuning() or {}),
            "session_id": deps.session_id,
            "run_id": deps.run_id,
        },
    )


def _coerce_int(value: object | None) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _string_sequence(value: object | None) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if item]
    return []


def _repair_single_result(
    item: SearchResult,
    row: Mapping[str, object],
) -> SearchResult | None:
    title = item.title or _build_title(row)
    url = item.url or _build_url(row)
    snippet = _resolve_snippet(item.snippet, row)
    if not snippet:
        return None
    metadata, metadata_changed = _merge_metadata(item.metadata, row)
    if title == item.title and url == item.url and snippet == item.snippet and not metadata_changed:
        return item
    return replace(item, title=title, url=url, snippet=snippet, metadata=metadata)


def _resolve_snippet(snippet: str, row: Mapping[str, object]) -> str:
    if snippet and snippet.strip():
        return snippet
    fallback = _build_snippet(row)
    if fallback.strip():
        return fallback
    raw = str(row.get("content") or row.get("preview") or "")
    return raw[:400]


def _merge_metadata(
    metadata_in: Mapping[str, object],
    row: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    metadata = dict(metadata_in)
    changed = False
    if not str(metadata.get("uri") or "").strip():
        metadata["uri"] = str(row.get("uri") or "")
        changed = True
    row_lang = str(row.get("lang") or "")
    if row_lang and not str(metadata.get("lang") or "").strip():
        metadata["lang"] = row_lang
        changed = True
    for meta_key, row_key in (
        ("start_line", "start_line"),
        ("end_line", "end_line"),
        ("start_byte", "start_byte"),
        ("end_byte", "end_byte"),
    ):
        if isinstance(metadata.get(meta_key), int):
            continue
        value = row.get(row_key)
        if value is None:
            continue
        metadata[meta_key] = _coerce_int(value)
        changed = True
    return metadata, changed


@dataclass(slots=True, frozen=True)
class _RepairStats:
    """Aggregate counters describing validator repairs."""

    inspected: int
    repaired: int
    dropped: int


def post_search_validate_and_fill(
    items: Sequence[SearchResult],
    *,
    hydration: HydrationPayload,
) -> tuple[list[SearchResult], _RepairStats]:
    """Ensure MCP results have required metadata, dropping corrupt rows.

    This function validates and repairs search results by ensuring each item has
    required metadata fields (URI, line ranges, content) from the hydration payload.
    It is called after search execution to ensure result quality and completeness
    before returning results to clients.

    Parameters
    ----------
    items : Sequence[SearchResult]
        Sequence of search result items to validate and repair.
    hydration : HydrationPayload
        Payload containing chunk metadata rows keyed by chunk ID, used to fill
        missing fields in search results.

    Returns
    -------
    tuple[list[SearchResult], _RepairStats]
        Tuple of repaired results and aggregate statistics describing how many
        rows were inspected, repaired, or dropped.
    """
    inspected = dropped = repaired = 0
    fixed: list[SearchResult] = []
    rows = hydration.rows
    for item in items:
        inspected += 1
        row = rows.get(item.chunk_id)
        if row is None:
            dropped += 1
            continue
        repaired_item = _repair_single_result(item, row)
        if repaired_item is None:
            dropped += 1
            continue
        if repaired_item is not item:
            repaired += 1
        fixed.append(repaired_item)
    return fixed, _RepairStats(inspected=inspected, repaired=repaired, dropped=dropped)


__all__ = [
    "FetchDependencies",
    "FetchObjectResult",
    "FetchRequest",
    "FetchResponse",
    "SearchDependencies",
    "SearchFilters",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "post_search_validate_and_fill",
    "run_fetch",
    "run_search",
]
