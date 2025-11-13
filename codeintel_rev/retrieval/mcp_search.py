"""Deep-Research compatible search/fetch orchestration helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

import numpy as np

from codeintel_rev.eval.pool_writer import PoolRow, write_pool
from codeintel_rev.io.faiss_manager import SearchRuntimeOverrides
from codeintel_rev.metrics.registry import (
    MCP_FETCH_LATENCY_SECONDS,
    MCP_SEARCH_LATENCY_SECONDS,
    MCP_SEARCH_POSTFILTER_DENSITY,
)
from codeintel_rev.typing import NDArrayF32, NDArrayI64
from kgfoundry_common.errors import EmbeddingError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.io.duckdb_catalog import StructureAnnotations
    from codeintel_rev.mcp_server.schemas import SearchFilterPayload
    from codeintel_rev.observability.timeline import Timeline
else:  # pragma: no cover - annotations only
    Timeline = None
    StructureAnnotations = object  # type: ignore[assignment]
    SearchFilterPayload = Mapping[str, Sequence[str]]  # type: ignore[assignment]

type EmbeddingVector = Sequence[float] | NDArrayF32

LOGGER = get_logger(__name__)


class EmbeddingClient(Protocol):
    """Protocol describing the minimal embedder surface needed for search."""

    def embed_single(self, text: str) -> EmbeddingVector:
        """Return a single embedding vector for ``text``."""
        ...


class IndexConfigLike(Protocol):
    """PEP 544 view of the index configuration needed by MCP search."""

    vec_dim: int
    faiss_nprobe: int


class LimitsConfigLike(Protocol):
    """PEP 544 view of server limit configuration."""

    max_results: int
    semantic_overfetch_multiplier: int


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

    def get_structure_annotations(
        self, ids: Sequence[int]
    ) -> dict[int, StructureAnnotations]:
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
        catalog: CatalogLike | None = None,
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
        payload: Mapping[str, Sequence[str]] | None,
    ) -> SearchFilters:
        """Normalize the incoming JSON payload into immutable tuples.

        Returns
        -------
        SearchFilters
            Filter payload with tuple-backed sequences.
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


@dataclass(slots=True)
class SearchResult:
    """Single search result entry."""

    chunk_id: int
    title: str
    url: str
    snippet: str
    score: float
    source: str
    metadata: dict[str, object]


@dataclass(slots=True)
class SearchResponse:
    """Structured search response returned to MCP adapters."""

    query_echo: str
    top_k: int
    results: list[SearchResult]
    limits: list[str]


@dataclass(slots=True)
class HydrationPayload:
    """Bundle of hydrated rows and structural annotations."""

    rows: Mapping[int, dict]
    annotations: Mapping[int, object]


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


@dataclass(slots=True)
class FetchObjectResult:
    """Single hydrated chunk."""

    chunk_id: int
    title: str
    url: str
    content: str
    metadata: dict[str, object]


@dataclass(slots=True)
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

    Returns
    -------
    SearchResponse
        Dataclass containing search hits and diagnostic metadata.
    """
    start = perf_counter()
    vector = _embed_query(deps.embedder, request.query, deps.settings.index.vec_dim)
    faiss_k = _compute_fanout(request.top_k, request.filters, deps.settings.limits)
    runtime = _build_runtime_overrides(rerank=request.rerank)
    distances, identifiers = deps.faiss.search(
        vector,
        k=faiss_k,
        nprobe=deps.settings.index.faiss_nprobe,
        runtime=runtime,
        catalog=deps.catalog if request.rerank else None,
    )
    ranked_ids = _flatten_ids(identifiers)
    ranked_scores = _flatten_scores(distances)
    chunk_rows, filtered_count = _hydrate_chunks(
        deps.catalog,
        ranked_ids,
        request.filters,
    )
    structure_map = deps.catalog.get_structure_annotations(chunk_rows.keys()) if chunk_rows else {}
    source_label = f"faiss_{deps.faiss.faiss_family or 'auto'}"
    results = _build_results(
        ranked_ids,
        ranked_scores,
        rows=chunk_rows,
        annotations=structure_map,
        request=request,
        source_label=source_label,
    )
    duration = max(perf_counter() - start, 0.0)
    MCP_SEARCH_LATENCY_SECONDS.observe(duration)
    _record_postfilter_density(filtered_count, len(ranked_ids))
    _write_pool_rows(results, deps, structure_map)
    _log_search_completion(request, deps, len(results), faiss_k)
    return SearchResponse(
        query_echo=request.query,
        top_k=request.top_k,
        results=results,
        limits=list(deps.limits),
    )


def run_fetch(*, request: FetchRequest, deps: FetchDependencies) -> FetchResponse:
    """Hydrate chunk content and metadata for the MCP fetch tool.

    Returns
    -------
    FetchResponse
        Dataclass containing hydrated chunk objects.
    """
    start = perf_counter()
    if not request.object_ids:
        return FetchResponse(objects=[])
    rows = deps.catalog.query_by_ids(request.object_ids)
    by_id = {int(row["id"]): row for row in rows}
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
    return FetchResponse(objects=objects)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _normalize_str_list(values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _embed_query(embedder: EmbeddingClient, query: str, vec_dim: int) -> NDArrayF32:
    try:
        vector = embedder.embed_single(query)
    except (RuntimeError, ValueError) as exc:  # pragma: no cover - network errors
        msg = "Embedding service unavailable"
        raise EmbeddingError(msg, cause=exc) from exc
    array = np.asarray(vector, dtype=np.float32).reshape(1, -1)
    if array.shape[1] != vec_dim:
        msg = f"Embedding dimension mismatch: expected {vec_dim}, got {array.shape[1]}"
        raise EmbeddingError(msg)
    return array


def _compute_fanout(top_k: int, filters: SearchFilters, limits: LimitsConfigLike) -> int:
    multiplier = (
        limits.semantic_overfetch_multiplier
        if (filters.has_path_filters or filters.has_language_filters or filters.symbols)
        else 1
    )
    return max(top_k, min(limits.max_results, top_k * max(1, multiplier)))


def _build_runtime_overrides(*, rerank: bool) -> SearchRuntimeOverrides | None:
    """Return FAISS runtime overrides derived from the rerank flag."""

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
) -> tuple[dict[int, dict[str, object]], int]:
    if not chunk_ids:
        return {}, 0
    if filters.has_path_filters or filters.has_language_filters:
        rows = catalog.query_by_filters(
            chunk_ids,
            include_globs=list(filters.include) or None,
            exclude_globs=list(filters.exclude) or None,
            languages=list(filters.languages) or None,
        )
    else:
        rows = catalog.query_by_ids(chunk_ids)
    chunk_map = {int(row["id"]): row for row in rows if row.get("id") is not None}
    return chunk_map, len(chunk_map)


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
    chunk_symbols = row.get("symbols")
    if not chunk_symbols:
        return False
    normalized = {str(symbol) for symbol in chunk_symbols if symbol}
    return any(symbol in normalized for symbol in symbols)


def _build_metadata(
    row: Mapping[str, object],
    annotation: StructureAnnotations | None,
    request: SearchRequest,
    score: float,
) -> dict[str, object]:
    metadata = {
        "uri": str(row.get("uri")),
        "start_line": int(row.get("start_line") or 0),
        "end_line": int(row.get("end_line") or 0),
        "start_byte": int(row.get("start_byte") or 0),
        "end_byte": int(row.get("end_byte") or 0),
        "lang": str(row.get("lang") or ""),
        "symbols": list(row.get("symbols") or ()),
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
        chunk_symbols = {str(sym) for sym in metadata.get("symbols", []) if sym}
        matched = sorted(chunk_symbols & set(request.filters.symbols))
        reasons.extend(f"symbol:name:{symbol}" for symbol in matched)
    if request.rerank:
        reasons.append("rerank:exact")
    reasons.append(f"score:{score:.3f}")
    return reasons


def _build_title(row: Mapping[str, object]) -> str:
    uri = str(row.get("uri") or "")
    start_line = int(row.get("start_line") or 0) + 1
    end_line = int(row.get("end_line") or start_line - 1) + 1
    return f"{uri}: lines {start_line}-{max(start_line, end_line)}"


def _build_url(row: Mapping[str, object]) -> str:
    uri = str(row.get("uri") or "")
    start_line = int(row.get("start_line") or 0) + 1
    end_line = int(row.get("end_line") or start_line - 1) + 1
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
        "start_line": int(row.get("start_line") or 0),
        "end_line": int(row.get("end_line") or 0),
        "start_byte": int(row.get("start_byte") or 0),
        "end_byte": int(row.get("end_byte") or 0),
        "lang": str(row.get("lang") or ""),
    }


def _write_pool_rows(
    results: Sequence[SearchResult], deps: SearchDependencies, annotations: Mapping[int, object]
) -> None:
    if not results or deps.pool_dir is None:
        return
    try:
        deps.pool_dir.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - filesystem tolerance
        return
    query_id = deps.run_id or uuid4().hex
    rows: list[PoolRow] = []
    for rank, result in enumerate(results, start=1):
        annotation = annotations.get(result.chunk_id)
        rows.append(
            PoolRow(
                query_id=query_id,
                channel="faiss",
                rank=rank,
                chunk_id=result.chunk_id,
                score=result.score,
                uri=str(result.metadata.get("uri")),
                symbol_hits=tuple(getattr(annotation, "symbol_hits", ()) or ()),
                ast_node_kinds=tuple(getattr(annotation, "ast_node_kinds", ()) or ()),
                cst_matches=tuple(getattr(annotation, "cst_matches", ()) or ()),
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
    "run_fetch",
    "run_search",
]
