"""Runtime helpers for executing searches against FAISS indexes."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import (
    FaissIndex,
    FaissModule,
    FaissParameterSpace,
    NDArrayF32,
    NDArrayI64,
    gate_import,
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
_SEARCH_RESULT_DIM = 2


@dataclass(frozen=True, slots=True)
class FAISSRuntimeOptions:
    """Runtime tuning knobs exposed by :class:`FAISSManager`."""

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
    if params and _set_parameter_space(index, params):
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

    if exact_rerank is not None and catalog is not None and refine_k_factor > 1.0 and search_k > k:
        reranked_d, reranked_i = exact_rerank(
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
