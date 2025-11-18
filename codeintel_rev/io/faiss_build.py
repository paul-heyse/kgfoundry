"""Builders for FAISS indexes used by :class:`FAISSManager`.

This module owns all responsibilities related to constructing, training, and
persisting FAISS indexes.  The public helpers encapsulate the adaptive index
selection logic that previously lived inside ``faiss_manager.py`` so that the
manager itself can focus on wiring, orchestration, and state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import FaissIndex, FaissModule, NDArrayF32, NDArrayI64, gate_import

_faiss = LazyModule("faiss", "FAISS builder operations")

IndexFamily = Literal["flat", "ivfflat", "ivfpq", "adaptive"]

_SMALL_CORPUS_THRESHOLD = 5_000
_MEDIUM_CORPUS_THRESHOLD = 50_000


@dataclass(frozen=True, slots=True)
class IndexBuildConfig:
    """Configuration for constructing the primary index."""

    vec_dim: int
    default_nlist: int = 8192
    family: IndexFamily = "adaptive"
    pq_m: int = 32
    pq_bits: int = 8
    opq_m: int = 0
    hnsw_m: int = 32


def _l2_normalize(vectors: NDArrayF32) -> NDArrayF32:
    """Return a float32 array with per-row L2 normalization applied.

    Parameters
    ----------
    vectors : NDArrayF32
        Raw embedding vectors.

    Returns
    -------
    NDArrayF32
        Normalized vectors with shape ``(n, dim)``.
    """
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True).astype(np.float32)
    norms[norms == 0] = 1.0
    return arr / norms


def _dynamic_nlist(n_vectors: int, *, cfg: IndexBuildConfig, minimum: int) -> int:
    """Return IVF nlist using the adaptive heuristic or configured default.

    Parameters
    ----------
    n_vectors : int
        Corpus size used to derive the centroid count.
    cfg : IndexBuildConfig
        Active builder configuration.
    minimum : int
        Lower bound to maintain for the centroid count.

    Returns
    -------
    int
        Centroid count suitable for IVFFlat/IVFPQ indexes.
    """
    if cfg.family != "adaptive":
        return max(cfg.default_nlist, minimum)
    if n_vectors <= 0:
        return minimum
    return max(int(np.sqrt(n_vectors)), minimum)


def choose_family(n_vectors: int, cfg: IndexBuildConfig) -> IndexFamily:
    """Select the index family given the corpus size and configuration.

    Parameters
    ----------
    n_vectors : int
        Corpus size used for heuristic selection.
    cfg : IndexBuildConfig
        Active builder configuration.

    Returns
    -------
    IndexFamily
        Selected family literal.
    """
    if cfg.family != "adaptive":
        return cfg.family
    if n_vectors < _SMALL_CORPUS_THRESHOLD:
        return "flat"
    if n_vectors <= _MEDIUM_CORPUS_THRESHOLD:
        return "ivfflat"
    return "ivfpq"


def _configure_direct_map(index: FaissIndex) -> None:
    """Best-effort enable direct map support on an ID-wrapped index."""
    try:
        if hasattr(index, "make_direct_map"):
            index.make_direct_map()
        inner = getattr(index, "index", None)
        if inner is not None and hasattr(inner, "make_direct_map"):
            inner.make_direct_map()
    except (AttributeError, RuntimeError):  # pragma: no cover - best effort
        return


def _factory_string_for(family: str, cfg: IndexBuildConfig) -> str:
    """Mirror the legacy factory string logic for explicit families.

    Parameters
    ----------
    family : str
        Requested FAISS family name.
    cfg : IndexBuildConfig
        Active builder configuration.

    Returns
    -------
    str
        Factory string suitable for ``faiss.index_factory``.
    """
    fam = family.lower()
    resolved_nlist = max(cfg.default_nlist, 1)
    if fam == "flat":
        return "Flat"
    if fam == "ivf_flat":
        return f"IVF{resolved_nlist},Flat"
    if fam == "ivf_pq":
        opq = f"OPQ{cfg.opq_m}," if cfg.opq_m > 0 else ""
        return f"{opq}IVF{resolved_nlist},PQ{cfg.pq_m}x{cfg.pq_bits}"
    if fam == "ivf_pq_refine":
        opq = f"OPQ{cfg.opq_m}," if cfg.opq_m > 0 else ""
        return f"{opq}IVF{resolved_nlist},PQ{cfg.pq_m}x{cfg.pq_bits},Refine(Flat)"
    if fam == "hnsw":
        return f"HNSW{cfg.hnsw_m}"
    return "Flat"


def _resolve_faiss_module() -> FaissModule:
    """Return the lazily imported FAISS module as a typed Protocol.

    Extended Summary
    ----------------
    Resolves the FAISS module via lazy import and casts it to the FaissModule
    Protocol type. This provides type-safe access to FAISS operations while
    deferring the actual import until needed.

    Returns
    -------
    FaissModule
        FAISS module instance conforming to the FaissModule Protocol interface.
        The module is lazily imported on first access.
    """
    return cast("FaissModule", _faiss.module())


def _build_adaptive_index(
    faiss_mod: FaissModule,
    vectors: NDArrayF32,
    cfg: IndexBuildConfig,
) -> tuple[FaissIndex, str]:
    """Construct an index using the adaptive family heuristic.

    Parameters
    ----------
    faiss_mod : FaissModule
        Resolved FAISS module implementing the builder operations.
    vectors : NDArrayF32
        Training vectors used for clustering.
    cfg : IndexBuildConfig
        Builder configuration describing defaults.

    Returns
    -------
    tuple[FaissIndex, str]
        Trained FAISS index and label describing the selected family.
    """
    n_vectors = len(vectors)
    if n_vectors < _SMALL_CORPUS_THRESHOLD:
        return faiss_mod.IndexFlatIP(cfg.vec_dim), "Flat"
    if n_vectors < _MEDIUM_CORPUS_THRESHOLD:
        nlist = _dynamic_nlist(n_vectors, cfg=cfg, minimum=100)
        quantizer = faiss_mod.IndexFlatIP(cfg.vec_dim)
        index = faiss_mod.IndexIVFFlat(
            quantizer,
            cfg.vec_dim,
            nlist,
            faiss_mod.METRIC_INNER_PRODUCT,
        )
        index.train(vectors)
        return index, f"IVF{nlist},Flat"
    nlist = _dynamic_nlist(n_vectors, cfg=cfg, minimum=1024)
    index_string = f"OPQ64,IVF{nlist},PQ64"
    index = faiss_mod.index_factory(cfg.vec_dim, index_string, faiss_mod.METRIC_INNER_PRODUCT)
    index.train(vectors)
    return index, index_string


def build_primary_index(
    vectors: NDArrayF32,
    *,
    cfg: IndexBuildConfig,
    override_family: IndexFamily | None = None,
) -> tuple[FaissIndex, str]:
    """Construct and train the primary FAISS index.

    Parameters
    ----------
    vectors : NDArrayF32
        Training vectors used to fit the index.
    cfg : IndexBuildConfig
        Builder configuration describing dimensions and heuristics.
    override_family : IndexFamily | None, optional
        Optional override for the family to build instead of the configured
        default.

    Returns
    -------
    tuple[FaissIndex, str]
        ID-mapped FAISS index and the descriptive factory label.

    Raises
    ------
    ValueError
        If the provided vectors do not match ``cfg.vec_dim``.
    """
    gate_import("faiss", "Building FAISS indexes")
    faiss_mod = _resolve_faiss_module()
    normalized = _l2_normalize(vectors)
    _, dims = normalized.shape
    if dims != cfg.vec_dim:
        msg = f"vec_dim mismatch: expected {cfg.vec_dim}, received {dims}"
        raise ValueError(msg)

    resolved_family = (override_family or cfg.family).lower()
    if resolved_family == "adaptive":
        base, label = _build_adaptive_index(faiss_mod, normalized, cfg)
    else:
        factory = _factory_string_for(resolved_family, cfg)
        base = faiss_mod.index_factory(cfg.vec_dim, factory, faiss_mod.METRIC_INNER_PRODUCT)
        if getattr(base, "is_trained", False) and not base.is_trained:
            base.train(normalized)
        label = factory

    id_map = faiss_mod.IndexIDMap2(base)
    _configure_direct_map(id_map)
    return id_map, label


def add_vectors(index: FaissIndex, vectors: NDArrayF32, ids: NDArrayI64) -> None:
    """Add normalized vectors with explicit IDs to the provided FAISS index.

    Parameters
    ----------
    index : FaissIndex
        Target FAISS index.
    vectors : NDArrayF32
        Vectors to add.
    ids : NDArrayI64
        External identifiers associated with each vector.
    """
    normalized = _l2_normalize(vectors)
    ids_arr = np.asarray(ids, dtype=np.int64).reshape(-1)
    gate_import("faiss", "Adding vectors to FAISS index")
    index.add_with_ids(normalized, ids_arr)


def save_index(index: FaissIndex, path: Path) -> None:
    """Persist a FAISS index to disk.

    Parameters
    ----------
    index : FaissIndex
        Index to serialize.
    path : Path
        Destination path for persistence.
    """
    gate_import("faiss", "Saving FAISS index")
    faiss_mod = _resolve_faiss_module()
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss_mod.write_index(index, str(path))


def load_index(path: Path) -> FaissIndex:
    """Load a FAISS index from disk.

    Parameters
    ----------
    path : Path
        Path to the serialized index.

    Returns
    -------
    FaissIndex
        Materialized FAISS index instance.
    """
    gate_import("faiss", "Loading FAISS index")
    faiss_mod = _resolve_faiss_module()
    return faiss_mod.read_index(str(path))


def extract_all_vectors(index: FaissIndex, vec_dim: int) -> tuple[NDArrayF32, NDArrayI64]:
    """Extract all vectors and IDs from a FAISS index.

    Reconstructs vectors from the index and retrieves their associated IDs.
    For quantized indexes (e.g., IVF-PQ), reconstruction returns approximate
    vectors (dequantized from the codebook).

    Parameters
    ----------
    index : FaissIndex
        FAISS index to extract vectors from. Must support `reconstruct()` and
        have an `id_map` attribute (IndexIDMap2 wrapper).
    vec_dim : int
        Vector dimension.

    Returns
    -------
    tuple[NDArrayF32, NDArrayI64]
        Tuple of (vectors, ids):
        - vectors: shape (n_vectors, vec_dim), dtype float32
        - ids: shape (n_vectors,), dtype int64

    Raises
    ------
    RuntimeError
        If the index does not support vector reconstruction or ID mapping.
    TypeError
        If the index's ``id_map`` interface is invalid.
    """
    n_vectors = int(getattr(index, "ntotal", 0))
    if n_vectors == 0:
        return np.empty((0, vec_dim), dtype=np.float32), np.empty(0, dtype=np.int64)

    _configure_direct_map(index)
    vectors = np.empty((n_vectors, vec_dim), dtype=np.float32)
    ids = np.empty(n_vectors, dtype=np.int64)

    # Check if index has id_map (IndexIDMap2 wrapper)
    if not hasattr(index, "id_map"):
        msg = (
            f"Index type {type(index).__name__} does not support ID mapping. "
            "Index must be wrapped with IndexIDMap2."
        )
        raise RuntimeError(msg)

    # Extract vectors and IDs
    id_map_obj = getattr(index, "id_map", None)
    if id_map_obj is None or not callable(getattr(id_map_obj, "at", None)):
        msg = f"Index type {type(index).__name__} has invalid id_map interface."
        raise TypeError(msg)
    at_callable = cast("Callable[[int], int]", id_map_obj.at)

    base_index = getattr(index, "index", index)
    for i in range(n_vectors):
        try:
            stored_id = int(at_callable(i))
            reconstructed = base_index.reconstruct(i)
            vectors[i] = np.asarray(reconstructed, dtype=np.float32)
            ids[i] = stored_id
        except (AttributeError, RuntimeError) as exc:
            msg = f"Failed to extract vector at index {i}: {exc}"
            raise RuntimeError(msg) from exc

    return vectors, ids


def merge_indexes(primary: FaissIndex, secondary: FaissIndex, vec_dim: int) -> FaissIndex:
    """Merge secondary index into primary index.

    Rebuilds the primary index to include all vectors from both indexes.
    This operation is expensive but improves search performance by consolidating
    the dual-index structure back into a single optimized index.

    Parameters
    ----------
    primary : FaissIndex
        Primary index to merge into.
    secondary : FaissIndex
        Secondary index to merge from.
    vec_dim : int
        Vector dimension.

    Returns
    -------
    FaissIndex
        New merged primary index.
    """
    # Extract vectors from both indexes
    primary_vectors, primary_ids = extract_all_vectors(primary, vec_dim)
    secondary_vectors, secondary_ids = extract_all_vectors(secondary, vec_dim)

    # Combine vectors and IDs
    all_vectors = np.vstack([primary_vectors, secondary_vectors])
    all_ids = np.concatenate([primary_ids, secondary_ids])

    # Build a new primary index with combined dataset
    cfg = IndexBuildConfig(vec_dim=vec_dim, family="adaptive")
    new_primary, _ = build_primary_index(all_vectors, cfg=cfg)

    # Add all vectors to the new primary index
    add_vectors(new_primary, all_vectors, all_ids)

    return new_primary


def create_secondary_index(vec_dim: int) -> FaissIndex:
    """Return a flat index used for incremental secondary ingestion.

    Parameters
    ----------
    vec_dim : int
        Vector dimensionality for the secondary index.

    Returns
    -------
    FaissIndex
        Newly constructed ``IndexIDMap2(IndexFlatIP)`` instance.
    """
    gate_import("faiss", "Creating FAISS secondary index")
    faiss_mod = _resolve_faiss_module()
    flat = faiss_mod.IndexFlatIP(vec_dim)
    wrapped = faiss_mod.IndexIDMap2(flat)
    _configure_direct_map(wrapped)
    return wrapped
