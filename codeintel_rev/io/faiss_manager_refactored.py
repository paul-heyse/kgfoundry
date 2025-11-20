"""FAISS manager thin facade for CPU vector search.

This module provides a high-level interface to adaptive FAISS indexes (Flat, IVFFlat,
or IVF-PQ) with CPU persistence. The actual implementation is delegated to three
specialized modules:
- faiss_build: Index lifecycle (build, train, add, merge)
- faiss_runtime: Query execution (search, knobs, tuning)
- faiss_store: Persistence and artifact management

Index type is automatically selected based on corpus size for optimal performance.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.errors import VectorIndexStateError
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    IndexFamily,
    build_primary_index,
)
from codeintel_rev.io.faiss_build import (
    add_vectors as builder_add_vectors,
)
from codeintel_rev.io.faiss_build import (
    create_secondary_index as builder_create_secondary,
)
from codeintel_rev.io.faiss_build import (
    load_index as builder_load_index,
)
from codeintel_rev.io.faiss_build import (
    merge_indexes as builder_merge_indexes,
)
from codeintel_rev.io.faiss_build import (
    save_index as builder_save_index,
)
from codeintel_rev.io.faiss_runtime import (
    FAISSRuntimeOptions,
    SearchRuntimeOverrides,
    apply_runtime_parameters,
)
from codeintel_rev.io.faiss_runtime import (
    search_dual as runtime_search_dual,
)
from codeintel_rev.io.faiss_store import (
    IndexArtifactPaths,
    export_idmap_parquet,
    get_idmap_array,
)
from codeintel_rev.io.faiss_store import (
    load_secondary_index as store_load_secondary,
)
from codeintel_rev.io.faiss_store import (
    save_secondary_index as store_save_secondary,
)
from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64

if TYPE_CHECKING:
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

# Lazy FAISS module
_faiss = LazyModule("faiss", "FAISS manager operations")
faiss = cast("Any", _faiss)


class FAISSManager:
    """FAISS index manager with adaptive indexing and incremental updates.

    Uses a dual-index architecture for fast incremental updates.

    **Primary Index** (built via `build_index()`):
    - Adaptive type selection based on corpus size
    - Small (<5K vectors): Flat index for exact search
    - Medium (5K-50K vectors): IVFFlat with dynamic nlist
    - Large (>50K vectors): IVF-PQ with dynamic nlist
    - Trained on initial corpus, expensive to rebuild

    **Secondary Index** (updated via `update_index()`):
    - Flat index (IndexFlatIP) for fast incremental additions
    - No training required - instant updates (seconds)
    - Used for new vectors added after initial build
    - Automatically searched alongside primary index

    Parameters
    ----------
    index_path : Path
        Path to CPU index file.
    vec_dim : int
        Vector dimension.
    nlist : int
        Number of IVF centroids (used as fallback for large corpora if dynamic
        calculation yields smaller value). For adaptive indexing, this parameter
        is typically overridden by dynamic nlist calculation.
    runtime : FAISSRuntimeOptions | None, optional
        Runtime configuration overrides for FAISS index behavior (nprobe, PQ
        shape, HNSW tuning). If None, uses default options from
        ``FAISSRuntimeOptions()``.
    """

    def __init__(
        self,
        index_path: Path,
        vec_dim: int = 3584,
        nlist: int = 8192,
        *,
        runtime: FAISSRuntimeOptions | None = None,
    ) -> None:
        """Initialize the FAISS manager.

        Parameters
        ----------
        index_path : Path
            Path where the primary index will be stored.
        vec_dim : int
            Vector dimensionality (default 3584 for multi-modal embeddings).
        nlist : int
            Number of IVF centroids as fallback (default 8192).
        runtime : FAISSRuntimeOptions | None
            Runtime tuning options. Defaults to FAISSRuntimeOptions().
        """
        self.index_path = Path(index_path)
        self.vec_dim = vec_dim
        self.nlist = nlist

        # Runtime configuration
        opts = runtime or FAISSRuntimeOptions()
        self.default_k = opts.default_k
        self.default_nprobe = opts.default_nprobe or 128
        self.hnsw_ef_search = opts.hnsw_ef_search
        self.refine_k_factor = opts.refine_k_factor
        self.autotune_on_start = opts.autotune_on_start
        self.runtime_opts = opts
        self.faiss_family: str | None = opts.faiss_family

        # Live indexes (private)
        self.cpu_index: FaissIndex | None = None
        self.secondary_index: FaissIndex | None = None
        self.incremental_ids: set[int] = set()

        # Runtime state
        self._runtime_overrides: dict[str, float] = {}
        self._tuning_lock = RLock()
        self._paths = IndexArtifactPaths(self.index_path)

    def build_index(self, vectors: NDArrayF32, *, family: IndexFamily | None = None) -> None:
        """Build and train FAISS index with adaptive type selection.

        Chooses the optimal index type based on corpus size:
        - Small corpus (<5K vectors): IndexFlatIP (exact search, no training)
        - Medium corpus (5K-50K vectors): IVFFlat with dynamic nlist
        - Large corpus (>50K vectors): IVF-PQ with dynamic nlist

        Parameters
        ----------
        vectors : NDArrayF32
            Training vectors, shape (n, vec_dim).
        family : IndexFamily | None, optional
            Override the adaptive family selection ("flat", "ivfflat", "ivfpq").
            If None, uses adaptive heuristic based on corpus size.

        Raises
        ------
        VectorIndexStateError
            If vectors is None or has invalid shape.
        """
        if vectors is None or vectors.size == 0:
            msg = "vectors must be a non-empty array"
            raise VectorIndexStateError(msg)

        resolved_family: IndexFamily = family or "adaptive"
        cfg = IndexBuildConfig(
            vec_dim=self.vec_dim,
            default_nlist=self.nlist,
            family=resolved_family,
        )
        index, _factory = build_primary_index(
            vectors,
            cfg=cfg,
            override_family=resolved_family,
        )
        self.cpu_index = index
        self.secondary_index = None
        self.incremental_ids.clear()
        self.faiss_family = resolved_family

    def add_vectors(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """Add vectors to the primary index after build.

        Parameters
        ----------
        vectors : NDArrayF32
            Vectors to add, shape (n, vec_dim).
        ids : NDArrayI64
            External chunk IDs for these vectors, shape (n,).

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized; call build_index() first."
            raise RuntimeError(msg)
        builder_add_vectors(self.cpu_index, vectors, ids)

    def update_index(self, new_vectors: NDArrayF32, new_ids: NDArrayI64) -> int:
        """Add vectors to the secondary (incremental) index.

        Parameters
        ----------
        new_vectors : NDArrayF32
            New vectors to add incrementally, shape (n, vec_dim).
        new_ids : NDArrayI64
            External chunk IDs, shape (n,).

        Returns
        -------
        int
            Number of vectors actually added (after deduplication).

        Raises
        ------
        RuntimeError
            If primary index is not loaded/built.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized. Run build_index() or load_cpu_index() first."
            raise RuntimeError(msg)

        self._ensure_secondary()

        # Deduplicate against tracked incremental IDs

        ids_arr = np.asarray(new_ids, dtype=np.int64).reshape(-1)
        vectors_arr = np.asarray(new_vectors, dtype=np.float32)
        keep_mask = np.ones_like(ids_arr, dtype=bool)
        seen = set()

        for pos, cid in enumerate(ids_arr.tolist()):
            if cid in seen or cid in self.incremental_ids:
                keep_mask[pos] = False
            else:
                seen.add(cid)

        kept = int(keep_mask.sum())
        if kept > 0:
            if self.secondary_index is None:
                msg = "Secondary index should be created but is None"
                raise RuntimeError(msg)
            builder_add_vectors(self.secondary_index, vectors_arr[keep_mask], ids_arr[keep_mask])
            self.incremental_ids.update(ids_arr[keep_mask].tolist())

        return kept

    def _ensure_secondary(self) -> None:
        """Lazily create secondary index (flat IP) for incremental updates."""
        if self.secondary_index is None:
            self.secondary_index = builder_create_secondary(self.vec_dim)

    def save_cpu_index(self) -> None:
        """Persist the primary CPU index to disk.

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        builder_save_index(self.cpu_index, self.index_path)

    def load_cpu_index(self) -> None:
        """Load the primary CPU index from disk."""
        self.cpu_index = builder_load_index(self.index_path)
        self.secondary_index = None
        self.incremental_ids.clear()
        self.faiss_family = self.runtime_opts.faiss_family

    def save_secondary_index(self) -> None:
        """Persist the secondary index to disk (.secondary suffix).

        Raises
        ------
        RuntimeError
            If secondary index is not created yet.
        """
        if self.secondary_index is None:
            msg = "Secondary index not created yet."
            raise RuntimeError(msg)
        store_save_secondary(self.secondary_index, self._paths)

    def load_secondary_index(self) -> None:
        """Load the secondary index from disk (.secondary suffix)."""
        try:
            self.secondary_index = store_load_secondary(self._paths)
        except FileNotFoundError:
            self.secondary_index = None

    def export_idmap(self, out_path: Path) -> int:
        """Export {faiss_row -> external_id} mapping to Parquet.

        Parameters
        ----------
        out_path : Path
            Output Parquet file path.

        Returns
        -------
        int
            Number of rows exported.

        Raises
        ------
        RuntimeError
            If primary index is not initialized or export fails.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return export_idmap_parquet(self.cpu_index, out_path)

    def get_idmap_array(self) -> NDArrayI64:
        """Get the ID map array from the primary index.

        Returns
        -------
        NDArrayI64
            Array of external chunk IDs.

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return get_idmap_array(self.cpu_index)

    def search(
        self,
        query: NDArrayF32,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: SearchRuntimeOverrides | None = None,
        catalog: object | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Execute dual-index search with optional exact rerank.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s), shape (1, vec_dim) or (n_queries, vec_dim).
        k : int | None, optional
            Number of results. Defaults to self.default_k.
        nprobe : int | None, optional
            IVF probe count override. Defaults to self.default_nprobe.
        runtime : SearchRuntimeOverrides | None, optional
            Runtime parameter overrides (ef_search, k_factor, etc.).
        catalog : object | None, optional
            Catalog for exact reranking. If provided, enables flat reranking.
            Typically a DuckDBCatalog instance, but typed as object for flexibility.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            (distances, indices) with shape (batch, k).

        Raises
        ------
        RuntimeError
            If primary index is not initialized or search fails.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)

        eff_k = int(k or self.default_k)
        eff_nprobe = int(nprobe or self.default_nprobe)

        k_factor = self.refine_k_factor
        if runtime is not None and runtime.k_factor is not None:
            k_factor = runtime.k_factor

        catalog_obj = cast("DuckDBCatalog | None", catalog)
        return runtime_search_dual(
            primary=self.cpu_index,
            secondary=self.secondary_index,
            query=query,
            k=eff_k,
            nprobe=eff_nprobe,
            refine_k_factor=k_factor,
            catalog=catalog_obj,
        )

    def apply_runtime_parameters(self, overrides: dict[str, float | int]) -> None:
        """Apply runtime parameter overrides to the active index.

        Parameters
        ----------
        overrides : dict[str, float | int]
            Dictionary with keys "nprobe", "efSearch", "quantizer_efSearch".
        """
        if self.cpu_index is None:
            return

        nprobe_value = overrides.get("nprobe")
        ef_search_value = overrides.get("efSearch")
        quantizer_value = overrides.get("quantizer_efSearch")
        apply_runtime_parameters(
            self.cpu_index,
            nprobe=int(nprobe_value) if nprobe_value is not None else None,
            ef_search=int(ef_search_value) if ef_search_value is not None else None,
            quantizer_ef_search=int(quantizer_value) if quantizer_value is not None else None,
        )

    def merge_indexes(self) -> None:
        """Merge secondary index into primary and rebuild.

        This is an expensive operation but improves query performance by
        consolidating the dual-index structure back into a single optimized index.

        Raises
        ------
        RuntimeError
            If primary index is not initialized or merge fails.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        if self.secondary_index is None:
            return

        self.cpu_index = builder_merge_indexes(self.cpu_index, self.secondary_index, self.vec_dim)
        self.secondary_index = None
        self.incremental_ids.clear()

    def require_cpu_index(self) -> FaissIndex:
        """Get the primary CPU index or raise if not initialized.

        Returns
        -------
        FaissIndex
            The primary index.

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return self.cpu_index

    def active_index(self) -> FaissIndex:
        """Get the currently active index (primary or secondary if primary unavailable).

        Returns
        -------
        FaissIndex
            The active index.

        Raises
        ------
        RuntimeError
            If no index is active.
        """
        if self.cpu_index is not None:
            return self.cpu_index
        if self.secondary_index is not None:
            return self.secondary_index
        msg = "No index is active."
        raise RuntimeError(msg)

    @property
    def tuning_lock(self) -> RLock:
        """Lock for runtime tuning mutations."""
        return self._tuning_lock

    @property
    def runtime_overrides(self) -> dict[str, float]:
        """Mutable runtime override dictionary."""
        return self._runtime_overrides


__all__ = ["FAISSManager", "FAISSRuntimeOptions"]
