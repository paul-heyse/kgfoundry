"""Runtime helpers for executing searches against FAISS indexes."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from numbers import Integral, Real
from time import perf_counter
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.runtime.imports import gate_import

if TYPE_CHECKING:
    import numpy as np
else:
    np = cast("ModuleType", LazyModule("numpy", "faiss runtime operations"))
from codeintel_rev.typing import (
    FaissIndex,
    FaissModule,
    FaissParameterSpace,
    NDArrayF32,
    NDArrayI64,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
else:  # pragma: no cover - runtime fallback
    DuckDBCatalog = Any

try:  # pragma: no cover - optional extra
    from codeintel_rev.retrieval.rerank_flat import exact_rerank
except (ImportError, ModuleNotFoundError):  # pragma: no cover - rerank path optional
    exact_rerank = None

_faiss = LazyModule("faiss", "FAISS runtime operations")


class ExactRerank(Protocol):
    """Protocol for exact reranking using DuckDB catalog.

    This protocol defines the interface for reranking candidate documents
    using exact similarity calculations from DuckDB embeddings.
    """

    def __call__(
        self,
        catalog: DuckDBCatalog,
        queries: NDArrayF32,
        candidate_ids: NDArrayI64,
        *,
        top_k: int,
        metric: str,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Rerank candidates using exact similarities from catalog.

        Parameters
        ----------
        catalog : DuckDBCatalog
            DuckDB catalog for querying exact embeddings.
        queries : NDArrayF32
            Query vectors to rerank against.
        candidate_ids : NDArrayI64
            Candidate document IDs to rerank.
        top_k : int
            Number of top results to return.
        metric : str
            Similarity metric ("ip" or "cosine").

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (scores, reranked_ids) arrays.
        """
        ...


_EXACT_RERANK_REF: list[ExactRerank | None] = [exact_rerank]


def _noop_parameter_space(_index: FaissIndex, _params: list[str]) -> bool:
    """No-op parameter space applier that always returns False.

    Parameters
    ----------
    _index : FaissIndex
        FAISS index (unused).
    _params : list[str]
        Parameter list (unused).

    Returns
    -------
    bool
        Always False (indicates no parameter space was applied).
    """
    return False


_PARAMETER_SPACE_APPLIER_REF: list[Callable[[FaissIndex, list[str]], bool]] = [
    _noop_parameter_space
]
_SEARCH_RESULT_DIM = 2


@dataclass(frozen=True, slots=True)
class FAISSRuntimeOptions:
    """Runtime tuning knobs exposed by :class:`FAISSManager`.

    Attributes
    ----------
    faiss_family : str | None, optional
        FAISS index family identifier ("ivf", "hnsw", etc.). "auto" selects
        based on index type. None means use index defaults. Defaults to "auto".
    pq_m : int, optional
        Number of subquantizers for Product Quantization (PQ). Must be positive.
        Defaults to 64.
    pq_nbits : int, optional
        Number of bits per PQ code. Must be positive. Defaults to 8.
    opq_m : int, optional
        Number of subquantizers for Optimized Product Quantization (OPQ). 0
        disables OPQ. Must be non-negative. Defaults to 0.
    default_nprobe : int | None, optional
        Default number of clusters to probe in IVF indexes. None means use
        index defaults. Must be positive if specified. Defaults to None.
    default_k : int, optional
        Default number of nearest neighbors to retrieve. Must be positive.
        Defaults to 50.
    hnsw_m : int, optional
        HNSW parameter M (number of bi-directional links per node). Must be
        positive. Defaults to 32.
    hnsw_ef_construction : int, optional
        HNSW ef_construction parameter (size of candidate list during
        construction). Must be positive. Defaults to 200.
    hnsw_ef_search : int, optional
        HNSW ef_search parameter (size of candidate list during search).
        Must be positive. Defaults to 128.
    refine_k_factor : float, optional
        Multiplier for refinement during search. Values > 1.0 retrieve more
        candidates before refinement. Must be positive. Defaults to 2.0.
    autotune_on_start : bool, optional
        Whether to run autotuning when the index is loaded. Defaults to False.
    enable_range_search : bool, optional
        Whether to enable range search (distance threshold) in addition to
        k-NN search. Defaults to False.
    semantic_min_score : float, optional
        Minimum similarity score threshold for semantic search results.
        Results below this threshold are filtered. Defaults to 0.0.
    """

    faiss_family: str | None = "auto"
    pq_m: int = 64
    pq_nbits: int = 8
    opq_m: int = 0
    default_nprobe: int | None = None
    default_k: int = 50
    hnsw_m: int = 32
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 128
    refine_k_factor: float = 2.0
    autotune_on_start: bool = False
    enable_range_search: bool = False
    semantic_min_score: float = 0.0


@dataclass(frozen=True, slots=True)
class SearchRuntimeOverrides:
    """Per-search overrides for HNSW/quantizer parameters.

    Attributes
    ----------
    ef_search : int | None, optional
        Override for HNSW ef_search parameter. None means use default from
        runtime options. Must be positive if specified. Defaults to None.
    quantizer_ef_search : int | None, optional
        Override for quantizer ef_search parameter. None means use default.
        Must be positive if specified. Defaults to None.
    k_factor : float | None, optional
        Override for refine_k_factor multiplier. None means use default from
        runtime options. Must be positive if specified. Defaults to None.
    """

    ef_search: int | None = None
    quantizer_ef_search: int | None = None
    k_factor: float | None = None


@dataclass(frozen=True, slots=True)
class RefineSearchConfig:
    """Configuration bundle for refine searches.

    Attributes
    ----------
    nprobe : int | None, optional
        Number of clusters to probe in IVF indexes. None means use default
        from runtime options. Must be positive if specified. Defaults to None.
    runtime : SearchRuntimeOverrides | None, optional
        Per-search runtime parameter overrides. None means use defaults from
        runtime options. Defaults to None.
    source : str, optional
        Source identifier for the search operation (e.g., "faiss", "refine").
        Used for observability and logging. Defaults to "faiss".
    """

    nprobe: int | None = None
    runtime: SearchRuntimeOverrides | None = None
    source: str = "faiss"


@dataclass(frozen=True, slots=True)
class _SearchExecutionParams:
    """Runtime parameters applied during dual search execution.

    Attributes
    ----------
    nprobe : int
        Number of clusters to probe in IVF indexes. Must be positive.
    ef_search : int | None
        HNSW ef_search parameter override. None means use default from runtime
        options. Must be positive if specified.
    quantizer_ef_search : int | None
        Quantizer ef_search parameter override. None means use default. Must be
        positive if specified.
    """

    nprobe: int
    ef_search: int | None
    quantizer_ef_search: int | None


@dataclass(frozen=True, slots=True)
class _SearchPlan:
    """Resolved parameters and query buffer for a search.

    Attributes
    ----------
    queries : NDArrayF32
        Query vectors as a 2D float32 array (n_queries, dim).
    k : int
        Number of nearest neighbors to retrieve. Must be positive.
    search_k : int
        Number of candidates to retrieve before refinement. Must be >= k.
    params : _SearchExecutionParams
        Runtime execution parameters (nprobe, ef_search, etc.).
    """

    queries: NDArrayF32
    k: int
    search_k: int
    params: _SearchExecutionParams


def _as2d_f32(arr: NDArrayF32) -> NDArrayF32:
    """Return array as ``float32`` with shape ``(batch, dim)``.

    Extended Summary
    ----------------
    Normalizes input vectors to float32 dtype and ensures 2D shape (batch, dim).
    Single vectors (1D) are reshaped to (1, dim). Vectors are L2-normalized
    to unit length, which is required for inner product similarity search.
    Zero vectors are handled by setting their norm to 1.0 to avoid division
    by zero.

    Parameters
    ----------
    arr : NDArrayF32
        Input vector(s). Can be 1D (single vector) or 2D (batch of vectors).
        Values are converted to float32 and L2-normalized.

    Returns
    -------
    NDArrayF32
        Float32 array with explicit batch dimension (batch, dim), where batch
        is 1 for single vectors or the original batch size. All vectors are
        L2-normalized to unit length.

    Notes
    -----
    Normalization is performed in-place where possible. Time complexity:
    O(batch * dim) for normalization. This function ensures vectors are
    compatible with FAISS inner product indexes which require normalized
    vectors.
    """
    data = np.asarray(arr, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    norms = np.linalg.norm(data, axis=1, keepdims=True).astype(np.float32)
    norms[norms == 0] = 1.0
    return data / norms


def apply_runtime_parameters(
    index: FaissIndex | None,
    *,
    nprobe: int | None,
    ef_search: int | None,
    quantizer_ef_search: int | None,
) -> None:
    """Best-effort application of runtime parameters to a FAISS index.

    Extended Summary
    ----------------
    Applies runtime tuning parameters to a FAISS index using the preferred
    ParameterSpace API when available, falling back to direct attribute
    assignment. This function handles parameter application gracefully,
    silently failing when parameters are not supported by the index type.
    Used to optimize search performance at runtime without rebuilding indexes.

    Parameters
    ----------
    index : FaissIndex | None
        Target FAISS index. If None, no operation is performed.
    nprobe : int | None
        IVF probe count override. Controls how many clusters are searched
        in IVF indexes. Higher values improve recall at the cost of speed.
        If None, no change is made.
    ef_search : int | None
        HNSW exploration factor. Controls candidate list size during search
        in HNSW indexes. Higher values improve recall at the cost of speed.
        If None, no change is made.
    quantizer_ef_search : int | None
        IVF quantizer exploration factor. Sets efSearch on the quantizer
        when it's an HNSW index. If None, no change is made.

    Notes
    -----
    This function attempts to use ParameterSpace first (preferred method),
    then falls back to direct attribute assignment. All operations are
    best-effort and silently handle unsupported parameters. No exceptions
    are raised if parameters cannot be applied.
    """
    if index is None:
        return
    gate_import("faiss", "Applying FAISS runtime parameters")
    params = _build_param_overrides(
        nprobe=nprobe,
        ef_search=ef_search,
        quantizer_ef_search=quantizer_ef_search,
    )
    applier = _PARAMETER_SPACE_APPLIER_REF[0]
    if params and applier(index, params):
        return
    _apply_attribute_fallbacks(
        index,
        nprobe=nprobe,
        ef_search=ef_search,
        quantizer_ef_search=quantizer_ef_search,
    )


def _build_param_overrides(
    *,
    nprobe: int | None,
    ef_search: int | None,
    quantizer_ef_search: int | None,
) -> list[str]:
    """Build parameter override strings for ParameterSpace API.

    Extended Summary
    ----------------
    Constructs a list of parameter assignment strings in key=value format
    suitable for passing to FAISS ParameterSpace.set_index_parameters().
    Only non-None parameters are included in the result.

    Parameters
    ----------
    nprobe : int | None
        IVF probe count to include in overrides. If None, omitted.
    ef_search : int | None
        HNSW efSearch value to include in overrides. If None, omitted.
    quantizer_ef_search : int | None
        Quantizer efSearch value to include in overrides. If None, omitted.

    Returns
    -------
    list[str]
        List of parameter strings in "key=value" format, e.g.,
        ["nprobe=64", "efSearch=128"]. Empty list if all parameters are None.
    """
    pairs: list[str] = []
    if nprobe is not None:
        pairs.append(f"nprobe={int(nprobe)}")
    if ef_search is not None:
        pairs.append(f"efSearch={int(ef_search)}")
    if quantizer_ef_search is not None:
        pairs.append(f"quantizer_efSearch={int(quantizer_ef_search)}")
    return pairs


def _set_parameter_space(index: FaissIndex, params: list[str]) -> bool:
    """Attempt to apply ParameterSpace overrides and return success.

    Parameters
    ----------
    index : FaissIndex
        Index to adjust.
    params : list[str]
        Parameter assignments expressed as strings.

    Returns
    -------
    bool
        ``True`` when ParameterSpace succeeded, ``False`` otherwise.
    """
    if not params:
        return False
    faiss_mod = cast("FaissModule", _faiss.module())
    ps_factory = getattr(faiss_mod, "ParameterSpace", None)
    if ps_factory is None:
        return False
    with suppress(Exception):  # pragma: no cover - best effort
        ps = cast("FaissParameterSpace", ps_factory())
        ps.initialize(index)
        ps.set_index_parameters(index, ",".join(params))
        return True
    return False


_PARAMETER_SPACE_APPLIER_REF[0] = _set_parameter_space


@contextmanager
def override_parameter_application(
    applier: Callable[[FaissIndex, list[str]], bool] | None,
) -> Iterator[None]:
    """Temporarily override the ParameterSpace application helper."""
    original = _PARAMETER_SPACE_APPLIER_REF[0]
    _PARAMETER_SPACE_APPLIER_REF[0] = applier or _noop_parameter_space
    try:
        yield
    finally:
        _PARAMETER_SPACE_APPLIER_REF[0] = original


@contextmanager
def override_exact_rerank(reranker: ExactRerank | None) -> Iterator[None]:
    """Temporarily replace the exact reranker used during dual searches."""
    previous = _EXACT_RERANK_REF[0]
    _EXACT_RERANK_REF[0] = reranker
    try:
        yield
    finally:
        _EXACT_RERANK_REF[0] = previous


def _assign_attr(target: object, attr: str, value: int | None) -> bool:
    """Assign ``attr`` on ``target`` when available.

    Extended Summary
    ----------------
    Attempts to set an attribute on a target object using setattr(). This is
    a best-effort operation that gracefully handles missing attributes or
    assignment failures. Used as a fallback when ParameterSpace API is
    unavailable for runtime parameter tuning.

    Parameters
    ----------
    target : object
        Object on which to set the attribute. Can be any object with
        settable attributes (e.g., FAISS index instances).
    attr : str
        Attribute name to set (e.g., "nprobe", "efSearch").
    value : int | None
        Integer value to assign. If None, no assignment is attempted.
        Must be positive if provided.

    Returns
    -------
    bool
        True if assignment succeeded, False when the attribute is missing,
        value is None, or the operation raised an exception.

    Notes
    -----
    This function uses suppress(Exception) to catch any errors during
    assignment, making it safe for best-effort parameter setting. Time
    complexity: O(1). No side effects beyond the attribute assignment.
    """
    if value is None or not hasattr(target, attr):
        return False
    with suppress(Exception):  # pragma: no cover - best effort
        setattr(target, attr, int(value))
        return True
    return False


def _set_nprobe(index: FaissIndex, value: int | None) -> bool:
    """Attempt to assign ``nprobe`` when present on the index.

    Extended Summary
    ----------------
    Sets the nprobe parameter on IVF (Inverted File) indexes if supported.
    The nprobe parameter controls how many clusters are searched during
    approximate nearest neighbor queries, trading off speed vs. recall.

    Parameters
    ----------
    index : FaissIndex
        FAISS index instance to configure.
    value : int | None
        nprobe value to set. If None, no change is made. Must be positive
        if provided.

    Returns
    -------
    bool
        True if nprobe was successfully set, False if the index doesn't
        support nprobe, value is None, or assignment failed.
    """
    return _assign_attr(index, "nprobe", value)


def _set_ef_search(index: FaissIndex, value: int | None) -> bool:
    """Attempt to assign ``efSearch`` on HNSW-like indexes.

    Extended Summary
    ----------------
    Sets the efSearch parameter on HNSW (Hierarchical Navigable Small World)
    indexes if supported. The efSearch parameter controls the size of the
    candidate list during search, affecting search quality and speed.

    Parameters
    ----------
    index : FaissIndex
        FAISS index instance to configure. Must be an HNSW index or support
        efSearch parameter.
    value : int | None
        efSearch value to set. If None, no change is made. Must be positive
        if provided.

    Returns
    -------
    bool
        True if efSearch was successfully set, False if the index doesn't
        support efSearch, value is None, or assignment failed.
    """
    return _assign_attr(index, "efSearch", value)


def _set_quantizer_ef_search(index: FaissIndex, value: int | None) -> bool:
    """Attempt to assign ``efSearch`` on the IVF quantizer when present.

    Extended Summary
    ----------------
    Sets the efSearch parameter on the quantizer of an IVF index when the
    quantizer is an HNSW index. This allows fine-tuning search parameters
    for hierarchical index structures where the quantizer itself is searchable.

    Parameters
    ----------
    index : FaissIndex
        FAISS index instance with a quantizer. The quantizer must support
        efSearch (typically an HNSW quantizer).
    value : int | None
        efSearch value to set on the quantizer. If None, no change is made.
        Must be positive if provided.

    Returns
    -------
    bool
        True if efSearch was successfully set on the quantizer, False if
        the index doesn't have a quantizer, the quantizer doesn't support
        efSearch, value is None, or assignment failed.
    """
    if value is None:
        return False
    quantizer = getattr(index, "quantizer", None)
    if quantizer is None:
        return False
    return _assign_attr(quantizer, "efSearch", value)


def _apply_attribute_fallbacks(
    index: FaissIndex,
    *,
    nprobe: int | None,
    ef_search: int | None,
    quantizer_ef_search: int | None,
) -> None:
    """Set runtime attributes directly when ParameterSpace is unavailable.

    Extended Summary
    ----------------
    Applies runtime parameters using direct attribute assignment as a fallback
    when the ParameterSpace API is not available or fails. This function calls
    the individual setter functions (_set_nprobe, _set_ef_search, etc.) which
    handle attribute existence checks and error suppression internally.

    Parameters
    ----------
    index : FaissIndex
        FAISS index instance to configure.
    nprobe : int | None
        IVF probe count to set via direct attribute assignment.
    ef_search : int | None
        HNSW efSearch value to set via direct attribute assignment.
    quantizer_ef_search : int | None
        Quantizer efSearch value to set via direct attribute assignment.

    Notes
    -----
    This is called after _set_parameter_space() fails or when ParameterSpace
    is unavailable. All operations are best-effort and silently handle
    unsupported attributes. No exceptions are raised.
    """
    _set_nprobe(index, nprobe)
    _set_ef_search(index, ef_search)
    _set_quantizer_ef_search(index, quantizer_ef_search)


def _run_index_search(
    index: FaissIndex, query: NDArrayF32, k: int
) -> tuple[NDArrayF32, NDArrayI64]:
    """Execute ``Index.search`` and coerce to float32/int64 outputs.

    Extended Summary
    ----------------
    Performs a FAISS index search operation and ensures results are returned
    in the expected dtype and shape. Query vectors are normalized and reshaped
    to 2D format before searching. Results are validated to be 2D arrays and
    coerced to float32 (distances) and int64 (identifiers) for consistency.

    Parameters
    ----------
    index : FaissIndex
        FAISS index instance to query. Must be trained and populated.
    query : NDArrayF32
        Query vectors. Can be 1D (single query) or 2D (batch of queries).
        Vectors are normalized and reshaped internally.
    k : int
        Number of nearest neighbors to retrieve per query. Must be positive
        and not exceed ntotal.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Tuple of (distances, identifiers) both with shape (batch, k) where
        batch is the number of queries. Distances are float32 similarity scores
        or distances. Identifiers are int64 candidate indices or external IDs.

    Raises
    ------
    RuntimeError
        If FAISS search returns arrays that are not two-dimensional. This
        indicates an unexpected FAISS behavior or index state.

    Notes
    -----
    This function wraps the FAISS search operation with normalization and
    type coercion. Time complexity depends on index type and k value.
    Query vectors are normalized via _as2d_f32() before searching.
    """
    gate_import("faiss", "Running FAISS search")
    q = _as2d_f32(query)
    distances, ids = index.search(q, k)
    dist_arr = np.asarray(distances, dtype=np.float32)
    id_arr = np.asarray(ids, dtype=np.int64)
    if dist_arr.ndim != _SEARCH_RESULT_DIM or id_arr.ndim != _SEARCH_RESULT_DIM:
        msg = "FAISS search results must be 2-D arrays."
        raise RuntimeError(msg)
    return dist_arr, id_arr


def _search_primary(
    index: FaissIndex, query: NDArrayF32, k: int, *, nprobe: int | None
) -> tuple[NDArrayF32, NDArrayI64]:
    """Search the primary index, applying ``nprobe`` when supported.

    Extended Summary
    ----------------
    Performs search on the primary FAISS index with optional nprobe parameter
    tuning. If nprobe is provided, it's applied to the index before searching
    to optimize IVF index performance. This allows runtime tuning of search
    quality vs. speed trade-offs.

    Parameters
    ----------
    index : FaissIndex
        Primary FAISS index instance to query. Must be trained and populated.
    query : NDArrayF32
        Query vectors. Can be 1D (single query) or 2D (batch of queries).
    k : int
        Number of nearest neighbors to retrieve per query. Must be positive.
    nprobe : int | None
        Optional IVF probe count override. If provided, sets nprobe on the
        index before searching. Higher values improve recall at the cost of
        speed. If None, uses the index's current nprobe setting.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Distances and identifiers for the search results, shape (batch, k).
        Distances are float32 similarity scores or distances. Identifiers are
        int64 candidate indices or external IDs.

    Notes
    -----
    The nprobe parameter only affects IVF indexes. For other index types,
    nprobe is ignored. Time complexity depends on index type, k, and nprobe
    (for IVF indexes). The nprobe setting persists for subsequent searches
    unless changed again.
    """
    if nprobe is not None:
        _set_nprobe(index, nprobe)
    return _run_index_search(index, query, k)


def _merge_by_score(
    dists1: NDArrayF32,
    ids1: NDArrayI64,
    dists2: NDArrayF32,
    ids2: NDArrayI64,
    k: int,
) -> tuple[NDArrayF32, NDArrayI64]:
    """Merge primary and secondary hits, deduplicating by candidate id.

    Extended Summary
    ----------------
    Combines search results from two indexes (primary and secondary), merging
    them by score and removing duplicate candidates based on identifier.
    Results are sorted by distance score (descending for inner product,
    ascending for L2) and truncated to the top k candidates per query.
    Used in dual-index search scenarios where results from multiple indexes
    need to be combined.

    Parameters
    ----------
    dists1 : NDArrayF32
        Distance/similarity scores from the primary index, shape (batch, n1).
    ids1 : NDArrayI64
        Candidate identifiers from the primary index, shape (batch, n1).
        Must match dists1 shape.
    dists2 : NDArrayF32
        Distance/similarity scores from the secondary index, shape (batch, n2).
    ids2 : NDArrayI64
        Candidate identifiers from the secondary index, shape (batch, n2).
        Must match dists2 shape.
    k : int
        Final number of candidates to return per query. Must be positive.
        Results are truncated to top k after merging and deduplication.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Merged distances and identifiers sorted by score, shape (batch, k).
        Distances are sorted descending (for inner product) or ascending
        (for L2). Invalid candidates (id < 0) are filtered out.

    Notes
    -----
    Duplicate candidates (same id appearing in both result sets) are handled
    by keeping the first occurrence based on the merged sort order. Time
    complexity: O(batch * (n1 + n2) * log(n1 + n2)) for sorting. Memory
    complexity: O(batch * k) for output arrays.
    """
    batch = dists1.shape[0]
    out_d = np.full((batch, k), np.finfo(np.float32).min, dtype=np.float32)
    out_i = np.full((batch, k), -1, dtype=np.int64)
    for row in range(batch):
        merged = list(zip(ids1[row].tolist(), dists1[row].tolist(), strict=True)) + list(
            zip(ids2[row].tolist(), dists2[row].tolist(), strict=True)
        )
        merged.sort(key=lambda item: item[1], reverse=True)
        seen: set[int] = set()
        out_pos = 0
        for candidate_id, score in merged:
            if candidate_id < 0 or candidate_id in seen:
                continue
            seen.add(candidate_id)
            out_d[row, out_pos] = score
            out_i[row, out_pos] = candidate_id
            out_pos += 1
            if out_pos == k:
                break
    return out_d, out_i


def search_dual(  # noqa: PLR0913
    *,
    primary: FaissIndex,
    secondary: FaissIndex | None,
    query: NDArrayF32,
    k: int,
    nprobe: int | None,
    refine_k_factor: float,
    catalog: DuckDBCatalog | None,
) -> tuple[NDArrayF32, NDArrayI64]:
    """Search the configured indexes and optionally perform exact rerank.

    Extended Summary
    ----------------
    Performs hybrid search across primary and optional secondary FAISS indexes,
    merging results and optionally applying exact reranking. This function
    implements a multi-stage retrieval pipeline: (1) search primary index with
    expanded k, (2) search secondary index if present and merge results,
    (3) optionally rerank using exact similarity from catalog, (4) return top k.

    Parameters
    ----------
    primary : FaissIndex
        Primary FAISS index instance. Must be trained and populated. This
        is the main index used for initial retrieval.
    secondary : FaissIndex | None
        Optional secondary FAISS index for incremental additions. If provided,
        results from both indexes are merged and deduplicated. If None, only
        primary index is searched.
    query : NDArrayF32
        Query vectors. Can be 1D (single query) or 2D (batch of queries).
        Vectors are normalized internally.
    k : int
        Target number of final results to return. Must be positive.
    nprobe : int | None
        IVF probe count override for the primary index. Higher values improve
        recall at the cost of speed. If None, uses index default.
    refine_k_factor : float
        Candidate expansion multiplier. Search retrieves refine_k_factor * k
        candidates before reranking. Values > 1.0 enable reranking with more
        candidates. Must be >= 1.0.
    catalog : DuckDBCatalog | None
        Catalog instance used for exact reranking when refine_k_factor > 1.0
        and exact_rerank is available. If None, reranking is skipped.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Distances and identifiers for the final result set, shape (batch, k).
        Results are sorted by score (descending for inner product). If reranking
        was performed, results reflect exact similarity scores from the catalog.

    Notes
    -----
    The search process: (1) searches primary index for refine_k_factor * k
    candidates, (2) searches secondary index if present and merges results
    with deduplication, (3) applies exact reranking if catalog and exact_rerank
    are available and refine_k_factor > 1.0, (4) returns top k results. Time
    complexity depends on index types, k, refine_k_factor, and whether reranking
    is performed. Reranking improves result quality at the cost of additional
    computation.
    """
    search_k = int(max(1.0, refine_k_factor) * k)
    d1, i1 = _search_primary(primary, query, search_k, nprobe=nprobe)
    if secondary is not None:
        d2, i2 = _run_index_search(secondary, query, search_k)
        d_m, i_m = _merge_by_score(d1, i1, d2, i2, search_k)
    else:
        d_m, i_m = d1, i1

    reranker = _EXACT_RERANK_REF[0]
    if reranker is not None and catalog is not None and refine_k_factor > 1.0 and search_k > k:
        reranked_d, reranked_i = reranker(
            catalog,
            _as2d_f32(query),
            i_m,
            top_k=k,
            metric="ip",
        )
        return (
            np.asarray(reranked_d, dtype=np.float32),
            np.asarray(reranked_i, dtype=np.int64),
        )

    return d_m[:, :k], i_m[:, :k]


def timed_search_with_params(
    index: FaissIndex,
    queries: NDArrayF32,
    k: int,
    param_str: str,
) -> tuple[float, tuple[NDArrayF32, NDArrayI64]]:
    """Execute a parameterized search and measure its latency.

    Extended Summary
    ----------------
    Performs a FAISS search with the specified parameter string and measures
    the execution time in milliseconds. Wraps the search operation with timing
    instrumentation, recording the elapsed time from start to completion. Used
    by autotune sweeps to evaluate parameter configurations and select optimal
    settings based on recall and latency trade-offs.

    Parameters
    ----------
    index : FaissIndex
        FAISS index to search. Must be trained and populated.
    queries : NDArrayF32
        Query vector(s) to search, shape (n_queries, vec_dim) or (vec_dim,).
        Automatically normalized for cosine similarity.
    k : int
        Number of nearest neighbors to return per query. Must be positive.
        Used to retrieve top-k results for evaluation.
    param_str : str
        FAISS ParameterSpace parameter string (e.g., "nprobe=64,efSearch=128").
        Applied to the index before search. Used to test different parameter
        configurations during autotune sweeps.

    Returns
    -------
    tuple[float, tuple[NDArrayF32, NDArrayI64]]
        Tuple containing:
        - Elapsed time in milliseconds (float): Search execution time measured
          using perf_counter() for high-resolution timing
        - Search results tuple: (distances, ids) arrays, both with shape (n_queries, k).
          Distances are cosine similarity scores; IDs are candidate indices or external IDs.

    Notes
    -----
    This function is used by AutoTuner.run_sweep() to evaluate parameter
    configurations during autotune sweeps. Time complexity: O(search_time)
    where search_time depends on index type and parameters, plus O(1) for
    timing overhead.
    """
    start = perf_counter()
    apply_runtime_parameters(index, nprobe=None, ef_search=None, quantizer_ef_search=None)
    if param_str and param_str.strip():
        faiss_mod = cast("FaissModule", _faiss.module())
        ps_factory = getattr(faiss_mod, "ParameterSpace", None)
        if ps_factory is not None:
            with suppress(Exception):  # pragma: no cover - best effort
                ps = cast("FaissParameterSpace", ps_factory())
                ps.initialize(index)
                ps.set_index_parameters(index, param_str)
    result = _run_index_search(index, queries, k)
    elapsed = (perf_counter() - start) * 1000.0
    return elapsed, result


def brute_force_truth_ids(queries: NDArrayF32, truths: NDArrayF32, k: int) -> NDArrayI64:
    """Compute ground-truth nearest neighbor IDs via exact brute-force search.

    Extended Summary
    ----------------
    Performs exact nearest neighbor search by computing the full similarity
    matrix (queries @ truths.T) and selecting the top-k most similar truth
    vectors for each query. It uses argpartition for efficient top-k selection
    without full sorting. The result provides ground-truth IDs for recall
    evaluation during autotune sweeps.

    Parameters
    ----------
    queries : NDArrayF32
        Query vectors with shape (n_queries, vec_dim) and dtype float32.
        Used to compute similarities against truth vectors. Vectors should be
        normalized for cosine similarity (inner product).
    truths : NDArrayF32
        Ground-truth vectors with shape (n_truths, vec_dim) and dtype float32.
        Used as the corpus for exact nearest neighbor search. Vectors should be
        normalized for cosine similarity. The number of truth vectors determines
        the maximum k value (clamped to n_truths).
    k : int
        Number of nearest neighbors to retrieve per query. Must be positive.
        Clamped to min(k, n_truths) to avoid exceeding the truth corpus size.
        When k <= 0 or k > n_truths, returns an empty array.

    Returns
    -------
    NDArrayI64
        Array of ground-truth nearest neighbor indices with shape (n_queries, k_eff)
        where k_eff = min(k, n_truths). Each row contains the indices (0-based) of
        the top-k most similar truth vectors for the corresponding query, sorted
        by similarity (descending). Returns an empty array with shape (n_queries, 0)
        when k <= 0 or n_truths == 0.

    Notes
    -----
    Time complexity: O(n_queries * n_truths * vec_dim) for similarity computation
    plus O(n_queries * n_truths * log(k)) for top-k selection. Space complexity:
    O(n_queries * n_truths) for the similarity matrix.
    """
    sims = queries @ truths.T
    k_eff = min(k, sims.shape[1])
    if k_eff <= 0:
        return np.empty((queries.shape[0], 0), dtype=np.int64)
    idx = np.argpartition(-sims, kth=k_eff - 1, axis=1)[:, :k_eff]
    return idx.astype(np.int64)


def estimate_recall(candidates: NDArrayI64, truth: NDArrayI64) -> float:
    """Compute average recall@k between candidate and ground-truth IDs.

    Parameters
    ----------
    candidates : NDArrayI64
        Candidate ID arrays with shape (n_queries, k).
    truth : NDArrayI64
        Ground-truth ID arrays with shape (n_queries, k).

    Returns
    -------
    float
        Average recall@k score in the range [0.0, 1.0]. Returns 0.0
        if either array is empty.
    """
    if candidates.size == 0 or truth.size == 0:
        return 0.0
    total = candidates.shape[0]
    hits = 0.0
    for found, expected in zip(candidates, truth, strict=False):
        truth_set = {int(val) for val in expected if int(val) >= 0}
        if not truth_set:
            continue
        hit_count = sum(1 for cand in found if int(cand) in truth_set)
        hits += float(hit_count) / len(truth_set)
    return hits / max(1, total)


def ensure_2d(array: NDArrayF32) -> NDArrayF32:
    """Normalize query arrays to shape (n_queries, vec_dim).

    Parameters
    ----------
    array : NDArrayF32
        Input array that may be 1-D or 2-D.

    Returns
    -------
    NDArrayF32
        Array guaranteed to be 2-D with shape (n_queries, vec_dim).
        If input is 1-D, reshaped to (1, vec_dim).
    """
    arr = np.asarray(array, dtype=np.float32)
    if arr.ndim == 1:
        return arr.reshape(1, -1)
    return arr


def _coerce_to_int(value: object, default: int = -1) -> int:
    """Safely round arbitrary objects to integers for index comparisons.

    Parameters
    ----------
    value : object
        Candidate value that might be converted to an integer.
    default : int
        Fallback value when conversion is not possible.

    Returns
    -------
    int
        Converted integer or the provided default.
    """
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _coerce_optional_int(value: object | None) -> int | None:
    """Return ``value`` coerced to int when possible.

    Parameters
    ----------
    value : object | None
        Value to coerce to an integer. Accepts integers, floats, or strings.
        Empty strings and ``None`` are converted to ``None``.

    Returns
    -------
    int | None
        Integer representation or ``None`` when the value is empty.

    Raises
    ------
    TypeError
        If ``value`` cannot be coerced to an integer.
    """
    if value is None:
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return int(stripped)
    msg = f"Unsupported integer override type: {type(value)!r}"
    raise TypeError(msg)


def _coerce_optional_float(value: object | None) -> float | None:
    """Return ``value`` coerced to float when possible.

    Parameters
    ----------
    value : object | None
        Value to coerce to a float. Accepts booleans, numeric types, or strings.
        Empty strings and ``None`` are converted to ``None``.

    Returns
    -------
    float | None
        Float representation or ``None`` when the value is empty.

    Raises
    ------
    TypeError
        If ``value`` cannot be coerced to a float.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return float(stripped)
    msg = f"Unsupported float override type: {type(value)!r}"
    raise TypeError(msg)
