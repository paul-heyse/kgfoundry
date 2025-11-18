"""Runtime helpers for executing searches against FAISS indexes."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import

if TYPE_CHECKING:  # pragma: no cover - typing only
    import faiss as _faiss_module

    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

    FaissIndex = _faiss_module.Index
else:  # pragma: no cover - runtime fallback
    DuckDBCatalog = Any
    FaissIndex = Any

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

    Parameters
    ----------
    arr : NDArrayF32
        Input vector(s).

    Returns
    -------
    NDArrayF32
        Float32 array with explicit batch dimension.
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

    Parameters
    ----------
    index : object
        Target FAISS index.
    nprobe : int | None
        IVF probe count override.
    ef_search : int | None
        HNSW exploration factor.
    quantizer_ef_search : int | None
        IVF quantizer exploration factor.
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
    index : object
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
    faiss_mod = _faiss.module()
    with suppress(Exception):  # pragma: no cover - best effort
        ps = faiss_mod.ParameterSpace()
        ps.initialize(index)
        ps.set_index_parameters(index, ",".join(params))
        return True
    return False


def _apply_attribute_fallbacks(
    index: FaissIndex,
    *,
    nprobe: int | None,
    ef_search: int | None,
    quantizer_ef_search: int | None,
) -> None:
    """Set runtime attributes directly when ParameterSpace is unavailable."""
    if nprobe is not None and hasattr(index, "nprobe"):
        with suppress(Exception):  # pragma: no cover - best effort
            index.nprobe = int(nprobe)
    if ef_search is not None and hasattr(index, "efSearch"):
        with suppress(Exception):  # pragma: no cover - best effort
            index.efSearch = int(ef_search)
    if quantizer_ef_search is not None and hasattr(index, "quantizer"):
        quantizer = getattr(index, "quantizer", None)
        if quantizer is not None and hasattr(quantizer, "efSearch"):
            with suppress(Exception):  # pragma: no cover - best effort
                quantizer.efSearch = int(quantizer_ef_search)


def _run_index_search(index: FaissIndex, query: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
    """Execute ``Index.search`` and coerce to float32/int64 outputs.

    Parameters
    ----------
    index : object
        Index to query.
    query : NDArrayF32
        Query vectors.
    k : int
        Candidate count.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Distances and identifiers with shape ``(batch, k)``.

    Raises
    ------
    RuntimeError
        If FAISS does not return two-dimensional arrays.
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

    Parameters
    ----------
    index : object
        Index to query.
    query : NDArrayF32
        Query vectors.
    k : int
        Candidate count.
    nprobe : int | None
        Optional IVF probe override.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Distances and identifiers for the search results.
    """
    if nprobe is not None and hasattr(index, "nprobe"):
        with suppress(Exception):
            index.nprobe = int(nprobe)
    return _run_index_search(index, query, k)


def _merge_by_score(
    dists1: NDArrayF32,
    ids1: NDArrayI64,
    dists2: NDArrayF32,
    ids2: NDArrayI64,
    k: int,
) -> tuple[NDArrayF32, NDArrayI64]:
    """Merge primary and secondary hits, deduplicating by candidate id.

    Parameters
    ----------
    dists1, ids1, dists2, ids2 : NDArrayF32 | NDArrayI64
        Distance/id pairs from each index.
    k : int
        Final candidate count.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Merged distances and identifiers sorted by score.
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

    Parameters
    ----------
    primary : object
        Primary FAISS index.
    secondary : object | None
        Optional secondary index for incremental adds.
    query : NDArrayF32
        Query vectors.
    k : int
        Target number of results.
    nprobe : int | None
        IVF probe override for the primary index.
    refine_k_factor : float
        Candidate expansion multiplier prior to rerank.
    catalog : object | None
        Catalog instance used for exact rerank (typically DuckDBCatalog).

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Distances and identifiers for the merged result set.
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
