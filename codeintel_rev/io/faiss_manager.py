"""FAISS manager for GPU-accelerated vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with cuVS acceleration,
CPU persistence, and GPU cloning. Index type is automatically selected based on
corpus size for optimal performance.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import perf_counter
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.metrics.registry import (
    FAISS_ANN_LATENCY_SECONDS,
    FAISS_BUILD_SECONDS_LAST,
    FAISS_BUILD_TOTAL,
    FAISS_INDEX_CODE_SIZE_BYTES,
    FAISS_INDEX_CUVS_ENABLED,
    FAISS_INDEX_DIM,
    FAISS_INDEX_GPU_ENABLED,
    FAISS_INDEX_SIZE_VECTORS,
    FAISS_REFINE_KEPT_RATIO,
    FAISS_REFINE_LATENCY_SECONDS,
    FAISS_SEARCH_ERRORS_TOTAL,
    FAISS_SEARCH_LAST_K,
    FAISS_SEARCH_LAST_MS,
    FAISS_SEARCH_NPROBE,
    FAISS_SEARCH_TOTAL,
    HNSW_SEARCH_EF,
    set_compile_flags_id,
    set_factory_id,
)
from codeintel_rev.observability.otel import as_span
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.retrieval.rerank_flat import exact_rerank
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import
from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    import faiss as _faiss
    import numpy as np

    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
else:
    np = cast("Any", LazyModule("numpy", "FAISS manager vector operations"))

try:  # optional heavy dependency
    import pyarrow as pa
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover - optional runtime extra
    pa = None
    pq = None

LOGGER = get_logger(__name__)
logger = LOGGER  # Alias for compatibility


class _LazyFaissProxy:
    """Deferred FAISS module loader to avoid import-time side effects."""

    __slots__ = ("_module",)

    def __init__(self) -> None:
        self._module: ModuleType | None = None

    def module(self) -> ModuleType:
        """Return the cached FAISS module, importing it on demand.

        Returns
        -------
        ModuleType
            Materialized FAISS module.
        """
        if self._module is None:
            imported = gate_import("faiss", "FAISS manager operations")
            self._module = cast("ModuleType", imported)
        return self._module

    def __getattr__(self, name: str) -> object:
        """Proxy attribute access to the underlying FAISS module.

        Parameters
        ----------
        name : str
            Attribute name to resolve from the proxied FAISS module.

        Returns
        -------
        object
            Attribute resolved from the proxied FAISS module.

        Notes
        -----
        This method enables transparent attribute access to FAISS module
        symbols without eagerly importing the module. The first access triggers
        lazy import via `gate_import()`.
        """
        return getattr(self.module(), name)


_FAISS_PROXY = _LazyFaissProxy()
faiss = cast("Any", _FAISS_PROXY)


def _faiss_module() -> ModuleType:
    """Return the lazily imported FAISS module.

    Returns
    -------
    ModuleType
        Cached FAISS module instance.
    """
    return _FAISS_PROXY.module()


def _has_faiss_gpu_support() -> bool:
    """Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.

    Returns
    -------
    bool
        ``True`` when GPU capabilities are available, otherwise ``False``.
    """
    try:
        module = _faiss_module()
    except ImportError:
        return False
    required_attrs = ("StandardGpuResources", "GpuClonerOptions", "index_cpu_to_gpu")
    return all(hasattr(module, attr) for attr in required_attrs)


# Adaptive indexing thresholds
_SMALL_CORPUS_THRESHOLD = 5000
_MEDIUM_CORPUS_THRESHOLD = 50000

_LOG_EXTRA_BASE: dict[str, object] = {"component": "faiss_manager"}


def _log_extra(**kwargs: object) -> dict[str, object]:
    """Build structured logging extras for FAISS manager events.

    Parameters
    ----------
    **kwargs : object
        Additional key-value pairs to include in logging extras. These are
        merged with the base component name.

    Returns
    -------
    dict[str, object]
        Merged dictionary with component name and provided kwargs.
    """
    return {**_LOG_EXTRA_BASE, **kwargs}


@dataclass(frozen=True, slots=True)
class FAISSRuntimeOptions:
    """Runtime tuning options passed to :class:`FAISSManager`."""

    faiss_family: str = "auto"
    pq_m: int = 64
    pq_nbits: int = 8
    opq_m: int = 0
    default_nprobe: int | None = None
    default_k: int = 50
    hnsw_m: int = 32
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 128
    refine_k_factor: float = 2.0
    use_gpu: bool = True
    gpu_clone_mode: str = "replicate"
    autotune_on_start: bool = False
    enable_range_search: bool = False
    semantic_min_score: float = 0.0


@dataclass(frozen=True, slots=True)
class SearchRuntimeOverrides:
    """Per-search overrides for HNSW/quantizer parameters."""

    ef_search: int | None = None
    quantizer_ef_search: int | None = None
    k_factor: float | None = None


@dataclass(frozen=True, slots=True)
class _SearchExecutionParams:
    """Runtime parameters applied during dual search execution."""

    nprobe: int
    ef_search: int | None
    quantizer_ef_search: int | None
    use_gpu: bool


@dataclass(frozen=True, slots=True)
class _SearchPlan:
    """Resolved parameters, query buffer, and timeline metadata for a search."""

    queries: NDArrayF32
    k: int
    search_k: int
    params: _SearchExecutionParams
    timeline: Timeline | None


class _FAISSIdMapMixin:
    """Mixin providing ID map export helpers."""

    def get_idmap_array(self) -> NDArrayI64:
        """Return the mapping from FAISS row IDs to external chunk IDs.

        Returns
        -------
        NDArrayI64
            Array where ``array[row]`` equals the external chunk ID.

        Raises
        ------
        RuntimeError
            If the primary index is not wrapped with IndexIDMap2.
        TypeError
            If the ID map interface is invalid.
        """
        manager = cast("FAISSManager", self)
        cpu_index = manager.require_cpu_index()
        id_map_obj = getattr(cpu_index, "id_map", None)
        if id_map_obj is None:
            msg = (
                "Primary index is not wrapped with IndexIDMap2; chunk hydration "
                "requires faiss.IndexIDMap2"
            )
            raise RuntimeError(msg)
        vector_to_array = getattr(faiss, "vector_to_array", None)
        if callable(vector_to_array):
            array = vector_to_array(id_map_obj)
            return np.asarray(array, dtype=np.int64)
        ntotal = cpu_index.ntotal
        ids = np.empty(ntotal, dtype=np.int64)
        at_callable = getattr(id_map_obj, "at", None)
        if not callable(at_callable):
            msg = "FAISS id_map does not expose vector_to_array() or at() helpers."
            raise TypeError(msg)
        id_accessor = cast("Callable[[int], int]", at_callable)
        for row in range(ntotal):
            ids[row] = int(id_accessor(row))
        return ids

    def export_idmap(self, out_path: Path) -> int:
        """Persist ``{faiss_row -> external_id}`` to Parquet and return row count.

        Parameters
        ----------
        out_path : Path
            Destination path for the Parquet sidecar.

        Returns
        -------
        int
            Number of ID rows exported.

        Raises
        ------
        RuntimeError
            If pyarrow is not available at runtime.
        """
        if pa is None or pq is None:  # pragma: no cover - optional dependency
            msg = "pyarrow is required to export ID maps"
            raise RuntimeError(msg)
        idmap = self.get_idmap_array()
        rows = np.arange(idmap.shape[0], dtype=np.int64)
        table = pa.Table.from_arrays(
            [
                pa.array(rows),
                pa.array(idmap),
                pa.array(["primary"] * len(rows)),
            ],
            names=["faiss_row", "external_id", "source"],
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
        LOGGER.info(
            "Exported FAISS ID map",
            extra=_log_extra(path=str(out_path), rows=int(idmap.shape[0])),
        )
        return int(idmap.shape[0])

    def hydrate_by_ids(self, catalog: DuckDBCatalog, ids: Sequence[int]) -> list[dict]:
        """Hydrate chunk metadata for ``ids`` via the provided DuckDB catalog.

        This method queries the DuckDB catalog to retrieve full chunk metadata
        (file paths, line numbers, text content, etc.) for a batch of chunk IDs.
        The IDs correspond to external chunk identifiers stored in the FAISS index,
        enabling retrieval of complete chunk information after vector search.

        Parameters
        ----------
        catalog : DuckDBCatalog
            DuckDB catalog instance providing query_by_ids() method for batch
            chunk metadata retrieval. The catalog must be initialized and connected
            to the same database containing chunk metadata.
        ids : Sequence[int]
            Sequence of external chunk IDs to hydrate. These IDs should match
            the IDs stored in the FAISS index (from add_vectors() or update_index()).
            Empty sequences return an empty list without querying the catalog.

        Returns
        -------
        list[dict]
            List of hydrated chunk metadata dictionaries, one per ID. Each dictionary
            contains chunk fields (id, uri, start_line, end_line, text, symbols, etc.)
            as defined by the DuckDB catalog schema. The list may be shorter than
            the input sequence if some IDs are not found in the catalog.

        Notes
        -----
        This method performs database queries via the DuckDB catalog. Time complexity:
        O(n) where n is the number of IDs, plus database query overhead. The method
        logs debug information including the count of IDs and index path for
        observability. Thread-safe if the catalog instance is thread-safe.
        """
        if not ids:
            return []
        manager = cast("FAISSManager", self)
        LOGGER.debug(
            "Hydrating chunk metadata",
            extra=_log_extra(count=len(ids), index=str(manager.index_path)),
        )
        return catalog.query_by_ids(list(ids))

    def reconstruct_batch(self, ids: Sequence[int]) -> NDArrayF32:
        """Reconstruct vectors for a batch of external chunk IDs.

        This method reconstructs the original embedding vectors for a batch of
        chunk IDs by querying the FAISS index. For quantized indexes (IVF-PQ),
        reconstruction returns approximate vectors (dequantized from the codebook).
        For flat indexes, reconstruction returns exact vectors. The method requires
        that the index supports direct map access for reconstruction.

        Parameters
        ----------
        ids : Sequence[int]
            Sequence of external chunk IDs to reconstruct vectors for. These IDs
            should match the IDs stored in the FAISS index. Empty sequences return
            an empty array with shape (0, vec_dim).

        Returns
        -------
        NDArrayF32
            Array of reconstructed vectors with shape ``(len(ids), vec_dim)``.
            Each row corresponds to one input ID. Vectors are float32 dtype and
            normalized for cosine similarity (L2-normalized). For quantized indexes,
            vectors are approximate reconstructions.

        Raises
        ------
        RuntimeError
            If the index does not support vector reconstruction (e.g., missing
            direct map, unsupported index type, or reconstruction fails for a
            specific ID). The error message includes the failing chunk ID for
            debugging.

        Notes
        -----
        This method requires that _configure_direct_map() has been called on
        the index to enable reconstruction. Time complexity: O(len(ids) * vec_dim)
        for reconstruction, plus index lookup overhead. The method performs no
        I/O operations and is thread-safe if the FAISS index is thread-safe.
        """
        manager = cast("FAISSManager", self)
        if not ids:
            return np.empty((0, manager.vec_dim), dtype=np.float32)
        cpu_index = manager.require_cpu_index()
        _configure_direct_map(cpu_index)
        vectors = np.empty((len(ids), manager.vec_dim), dtype=np.float32)
        for pos, chunk_id in enumerate(ids):
            try:
                vectors[pos] = cpu_index.reconstruct(int(chunk_id))
            except (AttributeError, RuntimeError) as exc:
                msg = f"Unable to reconstruct FAISS vector for chunk_id {chunk_id}"
                raise RuntimeError(msg) from exc
        return vectors


class FAISSManager(
    _FAISSIdMapMixin,
):  # lint-ignore[PLR0904]: manager orchestrates multiple subsystems
    """FAISS index manager with adaptive indexing, GPU support, and incremental updates.

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

    **Architecture Diagram**:
    ```
    Search Query
        |
        ├─> Primary Index (IVF-PQ/IVFFlat/Flat)
        |       └─> Returns top-k results
        |
        └─> Secondary Index (Flat) [if exists]
                └─> Returns top-k results
        |
        └─> Merge Results by Score
                └─> Return top-k combined results
    ```

    The secondary index is optional and controlled by usage of `update_index()`.
    When `update_index()` is called, the secondary index is automatically created
    if it doesn't exist. Use `merge_indexes()` periodically to merge secondary
    into primary and rebuild for optimal performance.

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
    use_cuvs : bool
        Enable cuVS acceleration.
    runtime : FAISSRuntimeOptions | None, optional
        Runtime configuration overrides for FAISS index behavior, including
        GPU settings, quantization parameters, and search tuning. If None,
        uses default options from `FAISSRuntimeOptions()`.
    """

    def __init__(
        self,
        index_path: Path,
        vec_dim: int = 2560,
        nlist: int = 8192,
        *,
        use_cuvs: bool = True,
        runtime: FAISSRuntimeOptions | None = None,
    ) -> None:
        self.index_path = index_path
        self.vec_dim = vec_dim
        self.nlist = nlist
        self.use_cuvs = use_cuvs
        opts = runtime or FAISSRuntimeOptions()
        self.faiss_family = opts.faiss_family
        self.pq_m = opts.pq_m
        self.pq_nbits = opts.pq_nbits
        self.opq_m = opts.opq_m
        self.default_nprobe = opts.default_nprobe or 128
        self.default_k = opts.default_k
        self.hnsw_m = opts.hnsw_m
        self.hnsw_ef_construction = opts.hnsw_ef_construction
        self.hnsw_ef_search = opts.hnsw_ef_search
        self.refine_k_factor = opts.refine_k_factor
        self.use_gpu = opts.use_gpu
        self.gpu_clone_mode = opts.gpu_clone_mode
        self.autotune_on_start = opts.autotune_on_start
        self.enable_range_search = opts.enable_range_search
        self.semantic_min_score = opts.semantic_min_score
        self.cpu_index: _faiss.Index | None = None
        self.gpu_index: _faiss.Index | None = None
        self.gpu_resources: _faiss.StandardGpuResources | None = None
        self.gpu_disabled_reason: str | None = None

        # Secondary index for incremental updates (dual-index architecture)
        self.secondary_index: _faiss.Index | None = None
        self.secondary_gpu_index: _faiss.Index | None = None
        self.incremental_ids: set[int] = set()
        # Secondary index path: same directory as primary, with .secondary suffix
        self.secondary_index_path = (
            index_path.parent / f"{index_path.stem}.secondary{index_path.suffix}"
        )
        self._tuned_parameters: dict[str, float | str] | None = None
        self._last_latency_ms: float | None = None
        self.autotune_profile_path = self.index_path.with_name("tuning.json")
        self._legacy_autotune_profile_path = self.index_path.with_suffix(".tune.json")
        self._meta_path = Path(f"{self.index_path}.meta.json")
        self._runtime_overrides: dict[str, float] = {}
        self._tuning_lock = RLock()

    def build_index(self, vectors: NDArrayF32, *, family: str | None = None) -> None:
        """Build and train FAISS index with adaptive type selection.

        Chooses the optimal index type based on corpus size:
        - Small corpus (<5K vectors): IndexFlatIP (exact search, no training)
        - Medium corpus (5K-50K vectors): IVFFlat with dynamic nlist
        - Large corpus (>50K vectors): IVF-PQ with dynamic nlist

        This adaptive selection provides 10-100x faster training for small/medium
        corpora while maintaining high recall (>95%) and search performance.

        Parameters
        ----------
        vectors : NDArrayF32
            Training vectors of shape (n, vec_dim). Vectors are automatically
            L2-normalized for cosine similarity.

        family : str | None, optional
            Override the configured FAISS family when building the index. When
            ``None`` the manager uses the configured family (or adaptive mode).

        Notes
        -----
        The index type is selected automatically based on the number of vectors.
        Small corpora use flat indexes (exact search) for simplicity and speed.
        Medium corpora use IVFFlat for balanced training time and recall.
        Large corpora use IVF-PQ for memory efficiency and fast search.

        Examples
        --------
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=2560)
        >>> vectors = np.random.randn(1000, 2560).astype(np.float32)
        >>> manager.build_index(vectors)
        >>> # Uses IndexFlatIP for 1000 vectors (small corpus)
        """
        faiss.normalize_L2(vectors)
        with self._tuning_lock:
            self._runtime_overrides.clear()

        build_start = perf_counter()
        n_vectors = len(vectors)
        resolved_family = (family or self.faiss_family or "auto").lower()
        if resolved_family == "auto":
            cpu_index, factory_label = self._build_adaptive_index(vectors, n_vectors)
        else:
            factory = self._factory_string_for(resolved_family, n_vectors)
            LOGGER.info(
                "Building FAISS index via factory",
                extra=_log_extra(
                    n_vectors=n_vectors,
                    factory=factory,
                    family=resolved_family,
                ),
            )
            cpu_index = faiss.index_factory(
                self.vec_dim,
                factory,
                faiss.METRIC_INNER_PRODUCT,
            )
            if getattr(cpu_index, "is_trained", False) and not cpu_index.is_trained:
                cpu_index.train(vectors)
            factory_label = factory

        # Log memory estimate
        mem_est = self.estimate_memory_usage(n_vectors)
        LOGGER.info(
            "Memory estimate for index",
            extra=_log_extra(
                n_vectors=n_vectors,
                cpu_index_bytes=mem_est["cpu_index_bytes"],
                gpu_index_bytes=mem_est["gpu_index_bytes"],
                total_bytes=mem_est["total_bytes"],
            ),
        )
        FAISS_INDEX_CODE_SIZE_BYTES.set(mem_est["cpu_index_bytes"])
        FAISS_INDEX_SIZE_VECTORS.set(n_vectors)
        FAISS_INDEX_DIM.set(self.vec_dim)
        FAISS_INDEX_CUVS_ENABLED.set(1 if self.use_cuvs else 0)

        # Wrap in IDMap for ID management
        cpu_id_map = faiss.IndexIDMap2(cpu_index)
        _configure_direct_map(cpu_id_map)
        self.cpu_index = cpu_id_map
        self._record_factory_choice(
            cpu_id_map,
            factory_label,
            parameter_space=self._format_parameter_string(self._runtime_overrides),
            vector_count=n_vectors,
        )
        FAISS_BUILD_TOTAL.inc()
        FAISS_BUILD_SECONDS_LAST.set(perf_counter() - build_start)

    def estimate_memory_usage(self, n_vectors: int) -> dict[str, int]:
        """Estimate memory usage in bytes for a given number of vectors.

        Provides memory estimates for CPU and GPU indexes based on the adaptive
        index type that would be selected for the given corpus size. This is useful
        for capacity planning and resource allocation.

        Parameters
        ----------
        n_vectors : int
            Number of vectors to estimate memory for.

        Returns
        -------
        dict[str, int]
            Dictionary with memory estimates in bytes:
            - ``cpu_index_bytes``: Estimated CPU index memory usage
            - ``gpu_index_bytes``: Estimated GPU index memory usage (includes ~20% overhead)
            - ``total_bytes``: Total estimated memory (CPU + GPU)

        Examples
        --------
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=2560)
        >>> estimates = manager.estimate_memory_usage(10000)
        >>> print(f"CPU index: {estimates['cpu_index_bytes'] / 1e9:.2f} GB")
        CPU index: 0.26 GB
        >>> print(f"Total: {estimates['total_bytes'] / 1e9:.2f} GB")
        Total: 0.57 GB

        Notes
        -----
        Memory estimates are approximate and may vary based on:
        - Actual index type selected (flat vs IVFFlat vs IVF-PQ)
        - FAISS internal overhead
        - GPU memory fragmentation
        - Operating system memory management

        Estimates are typically within ±20% of actual usage for most workloads.
        """
        vec_size = self.vec_dim * 4  # float32 = 4 bytes per dimension

        if n_vectors < _SMALL_CORPUS_THRESHOLD:
            # Flat index: stores all vectors directly
            cpu_mem = n_vectors * vec_size
        elif n_vectors < _MEDIUM_CORPUS_THRESHOLD:
            # IVFFlat: quantizer (nlist vectors) + inverted lists (n_vectors * 8 bytes overhead)
            nlist = min(int(np.sqrt(n_vectors)), n_vectors // 39)
            nlist = max(nlist, 100)
            cpu_mem = (nlist * vec_size) + (n_vectors * 8)  # 8 bytes overhead per vector
        else:
            # IVF-PQ: quantizer (nlist vectors) + PQ codes (n_vectors * 64 bytes)
            nlist = int(np.sqrt(n_vectors))
            nlist = max(nlist, 1024)
            cpu_mem = (nlist * vec_size) + (n_vectors * 64)  # 64 bytes per vector for PQ

        # GPU has ~20% overhead for memory management and buffers
        gpu_mem = int(cpu_mem * 1.2)

        return {
            "cpu_index_bytes": cpu_mem,
            "gpu_index_bytes": gpu_mem,
            "total_bytes": cpu_mem + gpu_mem,
        }

    def add_vectors(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """Add vectors with IDs to the index.

        Adds a batch of vectors to the FAISS index with their associated IDs.
        The vectors are normalized for cosine similarity (L2 normalization) before
        being added. IDs are used for retrieval - they should match the chunk IDs
        stored in DuckDB.

        This method requires that build_index() has been called first to create
        and train the index structure.

        Parameters
        ----------
        vectors : NDArrayF32
            Vectors to add, shape (n, vec_dim) where n is the number of vectors
            and vec_dim matches the index dimension. Dtype should be float32.
        ids : NDArrayI64
            Unique IDs for each vector, shape (n,). IDs are stored as int64 in
            FAISS. These should correspond to chunk IDs from the indexing pipeline.

        Raises
        ------
        RuntimeError
            If the index has not been built yet. Call build_index() first.
        """
        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError as exc:
            msg = "Cannot add vectors: FAISS index has not been built or loaded."
            raise RuntimeError(msg) from exc

        # Normalize vectors
        vectors_norm = vectors.copy()
        faiss.normalize_L2(vectors_norm)

        # Add with IDs
        cpu_index.add_with_ids(vectors_norm, ids.astype(np.int64))

    def update_index(self, new_vectors: NDArrayF32, new_ids: NDArrayI64) -> None:
        """Add new vectors to secondary index for fast incremental updates.

        Extended Summary
        ----------------
        This method adds new vectors to a secondary flat index (IndexFlatIP) which
        requires no training and provides instant updates. This enables fast incremental
        indexing without rebuilding the primary index. The method filters out vectors
        that already exist in the primary index to avoid duplicates, then adds only
        unique vectors to the secondary index. This is used for real-time index updates
        during active codebase indexing workflows.

        Parameters
        ----------
        new_vectors : NDArrayF32
            Array of new embedding vectors to add, shape (N, dim) where N is the number
            of vectors and dim matches the index dimensionality. Must be float32 and
            normalized if the index uses cosine similarity.
        new_ids : NDArrayI64
            Array of document/chunk IDs corresponding to new_vectors, shape (N,).
            Must be integer type. IDs that already exist in the primary index will be
            filtered out before adding to the secondary index.

        Raises
        ------
        RuntimeError
            If the secondary index is unexpectedly missing during the update. This
            indicates a configuration or initialization error that should be resolved
            before attempting updates.

        Notes
        -----
        Time complexity O(N * log(M)) where N is new_vectors count and M is existing
        index size, due to duplicate checking. Space complexity O(N) for temporary
        storage. The method performs I/O to update the FAISS index on disk. Thread-safe
        if called sequentially; concurrent updates may cause race conditions.
        """
        self._ensure_secondary_index()
        primary_contains = self._build_primary_contains()
        unique_indices = self._collect_unique_indices(new_ids, primary_contains)

        if not unique_indices:
            LOGGER.info(
                "All vectors already indexed in secondary index",
                extra=_log_extra(total=len(new_ids)),
            )
            return

        unique_vectors = new_vectors[unique_indices]
        unique_ids = new_ids[unique_indices]

        vectors_norm = unique_vectors.copy()
        faiss.normalize_L2(vectors_norm)

        secondary_index = self.secondary_index
        if secondary_index is None:
            msg = "Secondary index missing during update_index"
            raise RuntimeError(msg)
        secondary_index.add_with_ids(vectors_norm, unique_ids.astype(np.int64))
        self.incremental_ids.update(unique_ids.tolist())

        skipped = len(new_ids) - len(unique_ids)
        self._log_secondary_added(
            added=len(unique_ids),
            total_secondary_vectors=len(self.incremental_ids),
            skipped_duplicates=skipped,
        )

    def _ensure_secondary_index(self) -> None:
        if self.secondary_index is not None:
            return
        flat_index = faiss.IndexFlatIP(self.vec_dim)
        index = faiss.IndexIDMap2(flat_index)
        _configure_direct_map(index)
        self.secondary_index = index
        LOGGER.info(
            "Created secondary flat index for incremental updates",
            extra=_log_extra(event="secondary_index_created"),
        )

    def _build_primary_contains(self) -> Callable[[int], bool]:
        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError:
            return lambda _id: False

        id_map_obj = getattr(cpu_index, "id_map", None)
        if id_map_obj is None:
            return lambda _id: False

        for attr, builder in (
            ("contains", self._wrap_bool_contains),
            ("search", self._wrap_index_contains),
            ("find", self._wrap_index_contains),
        ):
            raw = getattr(id_map_obj, attr, None)
            if callable(raw):
                return builder(cast("Callable[[int], object]", raw))

        existing_ids = self._build_existing_ids_set(cpu_index, id_map_obj)
        return lambda id_val: int(id_val) in existing_ids

    @staticmethod
    def _wrap_bool_contains(raw: Callable[[int], object]) -> Callable[[int], bool]:
        """Wrap a raw contains function that returns a boolean-like value.

        This helper function wraps FAISS ID map contains methods that return
        boolean-like values (bool, int, etc.) and ensures they always return
        a proper boolean. The wrapper handles type conversion and exception
        handling to provide a robust contains check for ID lookups.

        Parameters
        ----------
        raw : Callable[[int], object]
            Raw contains function from FAISS ID map that accepts an integer ID
            and returns a boolean-like value (bool, int, etc.). The function
            may raise TypeError or ValueError for invalid inputs.

        Returns
        -------
        Callable[[int], bool]
            Wrapped contains function that always returns a bool. Returns False
            if the raw function raises an exception or returns a falsy value,
            True if the raw function returns a truthy value.

        Notes
        -----
        This wrapper is used to normalize FAISS ID map contains() methods that
        may return different types (bool, int) across FAISS versions. The
        wrapper ensures consistent boolean return values for duplicate checking
        in update_index(). Time complexity: O(1) per call, plus the cost of
        the underlying FAISS contains operation (typically O(1) for hash-based
        ID maps). The wrapper is thread-safe if the underlying raw function is
        thread-safe.
        """

        def contains(id_val: int) -> bool:
            """Check if an ID exists in the FAISS index.

            Parameters
            ----------
            id_val : int
                Document/chunk ID to check for existence in the index.

            Returns
            -------
            bool
                True if the ID exists in the index, False otherwise (including
                when the check fails due to type errors or invalid inputs).
            """
            try:
                return bool(raw(int(id_val)))
            except (TypeError, ValueError):
                return False

        return contains

    @staticmethod
    def _wrap_index_contains(raw: Callable[[int], object]) -> Callable[[int], bool]:
        """Wrap a raw contains function that returns an index position.

        This helper function wraps FAISS ID map contains methods that return
        index positions (non-negative integers) when an ID is found, or
        negative values when not found. The wrapper converts the result to a
        boolean by checking if the returned index is non-negative.

        Parameters
        ----------
        raw : Callable[[int], object]
            Raw contains function from FAISS ID map that accepts an integer ID
            and returns an index position (int >= 0 if found, < 0 if not found).
            The function may raise TypeError or ValueError for invalid inputs.

        Returns
        -------
        Callable[[int], bool]
            Wrapped contains function that returns True if the ID exists (index
            >= 0), False otherwise. Returns False if the raw function raises an
            exception or returns a value that coerces to a negative integer.

        Notes
        -----
        This wrapper is used to normalize FAISS ID map contains() methods that
        return index positions rather than booleans. The wrapper uses _coerce_to_int
        to safely convert the result and checks for non-negative values. Time
        complexity: O(1) per call, plus the cost of the underlying FAISS contains
        operation. The wrapper is thread-safe if the underlying raw function is
        thread-safe.
        """

        def contains(id_val: int) -> bool:
            """Check if an ID exists in the FAISS index by index position.

            Parameters
            ----------
            id_val : int
                Document/chunk ID to check for existence in the index.

            Returns
            -------
            bool
                True if the ID exists (raw function returns index >= 0), False
                otherwise (including when the check fails or returns a negative
                index).
            """
            try:
                result = raw(int(id_val))
            except (TypeError, ValueError):
                return False

            return _coerce_to_int(result) >= 0

        return contains

    @staticmethod
    def _build_existing_ids_set(cpu_index: _faiss.Index, id_map_obj: object) -> set[int]:
        try:
            n_total = cpu_index.ntotal
        except AttributeError:
            return set()

        try:
            if id_map_obj is None:
                return set()
            at_raw = getattr(id_map_obj, "at", None)
            if not callable(at_raw):
                return set()
            at_callable = cast("Callable[[int], int]", at_raw)
            return {int(at_callable(idx)) for idx in range(n_total)}
        except (AttributeError, TypeError, ValueError):
            return set()

    def _collect_unique_indices(
        self, new_ids: NDArrayI64, primary_contains: Callable[[int], bool]
    ) -> list[int]:
        unique_indices: list[int] = []
        seen_in_batch: set[int] = set()

        flat_ids = new_ids.reshape(-1)
        for offset, id_val in enumerate(flat_ids):
            id_int = int(id_val)
            if id_int in seen_in_batch:
                continue
            seen_in_batch.add(id_int)
            if id_int in self.incremental_ids:
                continue
            if primary_contains(id_int):
                continue
            unique_indices.append(offset)

        return unique_indices

    @staticmethod
    def _log_secondary_added(
        *,
        added: int,
        total_secondary_vectors: int,
        skipped_duplicates: int,
    ) -> None:
        LOGGER.info(
            "Added vectors to secondary index",
            extra=_log_extra(
                added=added,
                total_secondary_vectors=total_secondary_vectors,
                skipped_duplicates=skipped_duplicates,
            ),
        )

    def save_cpu_index(self) -> None:
        """Save CPU index to disk for persistence.

        Writes the current CPU index to the file specified by index_path. The
        index can be loaded later with load_cpu_index() to avoid rebuilding.
        The parent directory is created if it doesn't exist.

        The saved index includes all vectors and IDs that have been added. This
        is the CPU version - GPU indexes are cloned on-demand and not persisted.

        Raises
        ------
        RuntimeError
            If the index has not been built yet. Call build_index() first.
        """
        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError as exc:
            msg = "Cannot save index: FAISS index has not been built or loaded."
            raise RuntimeError(msg) from exc

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(cpu_index, str(self.index_path))

    def load_cpu_index(self) -> None:
        """Load CPU index from disk.

        Reads a previously saved FAISS index from index_path and loads it into
        memory. This allows reusing an index without rebuilding it, which is much
        faster for large indexes.

        After loading, you can call clone_to_gpu() to create a GPU version for
        faster search, or use search() directly with the CPU index.

        Raises
        ------
        FileNotFoundError
            If the index file does not exist at index_path. Ensure the index was
            saved with save_cpu_index() or that the path is correct.
        """
        if not self.index_path.exists():
            msg = f"Index not found: {self.index_path}"
            raise FileNotFoundError(msg)

        cpu_index = faiss.read_index(str(self.index_path))
        if not isinstance(cpu_index, faiss.IndexIDMap2):
            cpu_index = faiss.IndexIDMap2(cpu_index)
        _configure_direct_map(cpu_index)
        self.cpu_index = cpu_index
        FAISS_INDEX_SIZE_VECTORS.set(cpu_index.ntotal)
        FAISS_INDEX_DIM.set(self.vec_dim)
        FAISS_INDEX_GPU_ENABLED.set(0)
        self._load_tuned_profile()
        self._write_meta_snapshot(
            vector_count=cpu_index.ntotal,
            parameter_space=self._format_parameter_string(self._runtime_overrides),
        )

    def save_secondary_index(self) -> None:
        """Save secondary index to disk.

        Writes the current secondary index (if it exists) to a separate file
        alongside the primary index. The secondary index file uses the same
        name as the primary index with a `.secondary` suffix.

        This allows persisting incremental updates so they can be restored
        after restart. The secondary index is saved independently from the
        primary index.

        Raises
        ------
        RuntimeError
            If the secondary index has not been created yet. Call update_index()
            first to create the secondary index.
        """
        if self.secondary_index is None:
            msg = "Cannot save secondary index: secondary index has not been created."
            raise RuntimeError(msg)

        self.secondary_index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.secondary_index, str(self.secondary_index_path))
        LOGGER.info(
            "Persisted secondary FAISS index",
            extra=_log_extra(path=str(self.secondary_index_path)),
        )

    def load_secondary_index(self) -> None:
        """Load secondary index from disk.

        Reads a previously saved secondary FAISS index from disk and loads it
        into memory. This restores incremental updates that were made in a
        previous session.

        After loading, the secondary index will be automatically searched
        alongside the primary index when using search(). The incremental_ids
        set is restored from the index contents.

        Raises
        ------
        FileNotFoundError
            If the secondary index file does not exist. This is normal if no
            incremental updates have been made yet.
        """
        if not self.secondary_index_path.exists():
            msg = f"Secondary index not found: {self.secondary_index_path}"
            raise FileNotFoundError(msg)

        index = faiss.read_index(str(self.secondary_index_path))
        _configure_direct_map(index)
        self.secondary_index = index

        # Restore incremental_ids from the loaded index
        if self.secondary_index is not None:
            n_vectors = self.secondary_index.ntotal
            id_map_obj = getattr(self.secondary_index, "id_map", None)
            if id_map_obj is not None and callable(getattr(id_map_obj, "at", None)):
                at_callable = cast("Callable[[int], int]", id_map_obj.at)
                self.incremental_ids = {at_callable(i) for i in range(n_vectors)}
            else:
                self.incremental_ids = set(range(n_vectors))

        LOGGER.info(
            "Loaded secondary FAISS index",
            extra=_log_extra(
                path=str(self.secondary_index_path),
                vectors=len(self.incremental_ids),
            ),
        )

    def clone_to_gpu(self, device: int = 0) -> bool:
        """Clone CPU index to GPU for accelerated search.

        Creates a GPU-resident copy of the CPU index for faster search operations.
        The GPU index uses the same structure (IVF-PQ) but runs on GPU hardware
        for 10-100x speedup on large indexes.

        If cuVS acceleration is enabled (use_cuvs=True), the function attempts to
        use optimized cuVS kernels. If cuVS is unavailable, it falls back to
        standard FAISS GPU operations.

        The GPU index is kept in memory alongside the CPU index. Both can be
        used for search, but GPU is preferred when available.

        Parameters
        ----------
        device : int, optional
            CUDA device ID to use (default: 0). Use device 0 for single-GPU systems.
            For multi-GPU, specify the device ID (0, 1, 2, etc.).

        Returns
        -------
        bool
            ``True`` when GPU acceleration is available. ``False`` when GPU
            initialization fails and the manager falls back to the CPU index.

        Raises
        ------
        RuntimeError
            If the CPU index has not been loaded yet. Call load_cpu_index() or
            build_index() first.
        """
        if not self.use_gpu:
            FAISS_INDEX_GPU_ENABLED.set(0)
            self.gpu_disabled_reason = "GPU usage disabled by configuration"
            LOGGER.info(
                "Skipping GPU clone; disabled via configuration",
                extra=_log_extra(device=device, reason=self.gpu_disabled_reason),
            )
            return False

        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError as exc:
            msg = "Cannot clone index to GPU before building or loading it."
            raise RuntimeError(msg) from exc

        self.gpu_disabled_reason = None

        if not _has_faiss_gpu_support():
            self.gpu_disabled_reason = "FAISS GPU symbols unavailable - running in CPU mode"
            LOGGER.info(
                "Skipping GPU clone; FAISS GPU symbols unavailable",
                extra=_log_extra(reason=self.gpu_disabled_reason, device=device),
            )
            FAISS_INDEX_GPU_ENABLED.set(0)
            return False

        try:
            # Initialize GPU resources
            self.gpu_resources = faiss.StandardGpuResources()

            # Configure cloner options
            co = faiss.GpuClonerOptions()
            co.useFloat16 = False

            # Try with cuVS if enabled
            co.use_cuvs = False
            if self.use_cuvs:
                try:
                    self._try_load_cuvs()
                except (ImportError, RuntimeError, AttributeError) as exc:
                    LOGGER.warning(
                        "cuVS acceleration unavailable",
                        extra=_log_extra(reason=str(exc)),
                    )
                else:
                    co.use_cuvs = True

            self.gpu_index = faiss.index_cpu_to_gpu(self.gpu_resources, device, cpu_index, co)
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            self.gpu_resources = None
            self.gpu_index = None
            self.gpu_disabled_reason = f"FAISS GPU disabled - using CPU: {exc}"
            LOGGER.warning(
                "FAISS GPU initialization failed; continuing with CPU index",
                extra=_log_extra(reason=str(exc), device=device),
                exc_info=True,
            )
            FAISS_INDEX_GPU_ENABLED.set(0)
            return False

        FAISS_INDEX_GPU_ENABLED.set(1)
        return True

    def search(
        self,
        query: NDArrayF32,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: SearchRuntimeOverrides | None = None,
        catalog: DuckDBCatalog | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Search for nearest neighbors using cosine similarity with dual-index support.

        Performs approximate nearest neighbor search using the FAISS index(es).
        When a secondary index exists (from incremental updates), searches both
        the primary and secondary indexes, then merges results by score to return
        the top-k most similar vectors overall.

        The function automatically uses the GPU index if available (faster),
        otherwise falls back to CPU. The nprobe parameter controls the trade-off
        between search speed and recall - higher values search more cells and
        improve recall but slow down search.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s) of shape (n_queries, vec_dim) or (vec_dim,) for
            single query. Dtype should be float32. Vectors are automatically
            normalized for cosine similarity.
        k : int | None, optional
            Number of nearest neighbors to return per query. If None, uses
            `default_k` from runtime options (default: 50). Higher k improves
            recall but increases computation and memory usage.
        nprobe : int | None, optional
            Number of IVF cells to probe during search. If None, uses
            `default_nprobe` from runtime options. Higher values improve recall
            but slow down search. Should match or be less than the nlist parameter
            used during index construction. Only applies to IVF-family indexes.
        runtime : SearchRuntimeOverrides | None, optional
            Optional overrides controlling HNSW and refinement parameters.
        catalog : DuckDBCatalog | None, optional
            When provided and ``refine_k_factor`` > 1, candidate embeddings are
            hydrated from DuckDB and reranked exactly before returning results.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (distances, ids) arrays:
            - distances: shape (n_queries, k), cosine similarity scores (higher
              is more similar, range typically 0-1 after normalization)
            - ids: shape (n_queries, k), chunk IDs of the nearest neighbors.
              IDs correspond to the ids passed to add_vectors() or update_index().

        Raises
        ------
        VectorSearchError
            If the FAISS search fails on CPU or GPU (e.g., index unavailable,
            GPU failure, invalid parameters). The error contains context about
            the index path and GPU usage for observability.

        Notes
        -----
        When both primary and secondary indexes exist, the method:
        1. Searches primary index with nprobe parameter
        2. Searches secondary index (flat, no nprobe)
        3. Merges results by score (inner product distance)
        4. Returns top-k combined results

        This ensures incremental updates are immediately searchable without
        rebuilding the primary index. Time complexity depends on index type:
        O(n) for Flat, O(nprobe * k) for IVF-family, O(log n * ef_search) for HNSW.
        """
        plan = self._prepare_search_plan(query, k, nprobe, runtime)
        timeline = plan.timeline
        FAISS_SEARCH_TOTAL.inc()
        FAISS_SEARCH_LAST_K.set(float(plan.k))
        if plan.params.nprobe is not None:
            FAISS_SEARCH_NPROBE.set(float(plan.params.nprobe))
        if plan.params.ef_search is not None:
            HNSW_SEARCH_EF.set(float(plan.params.ef_search))
        if timeline is not None:
            timeline.event(
                "faiss.search.start",
                "faiss",
                attrs={
                    "k": plan.k,
                    "nprobe": plan.params.nprobe,
                    "use_gpu": plan.params.use_gpu,
                    "has_secondary": bool(self.secondary_index),
                },
            )

        start = perf_counter()
        family_label = getattr(self, "faiss_family", "auto")
        ann_timer_start = start
        try:
            distances, identifiers = self._execute_dual_search(
                query=plan.queries,
                search_k=plan.search_k,
                params=plan.params,
            )
            refined = self._maybe_refine_results(
                catalog=catalog,
                plan=plan,
                identifiers=identifiers,
            )
            if refined is not None:
                distances, identifiers = refined
            result = (distances[:, : plan.k], identifiers[:, : plan.k])
        except Exception as exc:
            if timeline is not None:
                timeline.event(
                    "faiss.search.end",
                    "faiss",
                    status="error",
                    message=str(exc),
                    attrs={
                        "k": plan.k,
                        "nprobe": plan.params.nprobe,
                        "use_gpu": plan.params.use_gpu,
                    },
                )
            FAISS_SEARCH_ERRORS_TOTAL.inc()
            msg = "FAISS search failed"
            raise VectorSearchError(
                msg,
                cause=exc,
                context={
                    "index_path": str(self.index_path),
                    "use_gpu": plan.params.use_gpu,
                    "search_k": plan.k,
                },
            ) from exc
        finally:
            duration = max(perf_counter() - ann_timer_start, 0.0)
            FAISS_ANN_LATENCY_SECONDS.labels(family=str(family_label)).observe(duration)

        elapsed_total = (perf_counter() - start) * 1000.0
        if timeline is not None:
            timeline.event(
                "faiss.search.end",
                "faiss",
                attrs={
                    "duration_ms": int(elapsed_total),
                    "rows": result[0].shape[0],
                    "k": plan.k,
                    "nprobe": plan.params.nprobe,
                    "use_gpu": plan.params.use_gpu,
                },
            )
        self._last_latency_ms = elapsed_total
        FAISS_SEARCH_LAST_MS.set(elapsed_total)
        return result

    def _prepare_search_plan(
        self,
        query: NDArrayF32,
        k: int | None,
        nprobe: int | None,
        runtime: SearchRuntimeOverrides | None,
    ) -> _SearchPlan:
        """Normalize query and resolve runtime knobs for a FAISS search.

        Extended Summary
        ----------------
        This helper method prepares a search plan by normalizing the query vector
        (L2 normalization), resolving effective k and search_k values, and applying
        runtime tuning overrides. It consolidates all search parameters into a
        _SearchPlan dataclass for consistent execution. Used internally by search()
        to prepare search parameters before executing FAISS queries.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s) to normalize and search. Shape (n_queries, vec_dim) or
            (vec_dim,). Normalized to unit length using L2 normalization.
        k : int | None
            Requested number of results. If None, uses default_k from settings.
        nprobe : int | None
            Optional override for number of IVF cells to probe. If None, uses
            default_nprobe or runtime overrides.
        runtime : SearchRuntimeOverrides | None
            Optional runtime tuning overrides (ef_search, quantizer_ef_search, k_factor).
            Applied to resolve final search parameters.

        Returns
        -------
        _SearchPlan
            Search plan containing normalized queries, effective k, search_k (with
            k_factor applied), and execution parameters (nprobe, ef_search, GPU flag).
            The plan is ready for use in FAISS search execution.

        Notes
        -----
        This method performs L2 normalization on query vectors and resolves all
        search parameters including k_factor expansion. Time complexity: O(n_queries * vec_dim)
        for normalization plus O(1) for parameter resolution.
        """
        self._require_cpu_index()
        normalized = self._ensure_2d(query).copy().astype(np.float32)
        faiss.normalize_L2(normalized)
        k_eff = max(1, int(k or self.default_k))
        runtime = runtime or SearchRuntimeOverrides()
        nprobe_eff, ef_eff, k_factor, quantizer_ef = self._resolve_search_knobs(
            override_nprobe=nprobe,
            override_ef=runtime.ef_search,
            override_k_factor=runtime.k_factor,
            override_quantizer=runtime.quantizer_ef_search,
        )
        search_k = max(k_eff, math.ceil(k_eff * max(1.0, k_factor)))
        resolved_nprobe = nprobe_eff if nprobe_eff is not None else self.default_nprobe
        if resolved_nprobe is None:
            resolved_nprobe = 1
        params = _SearchExecutionParams(
            nprobe=resolved_nprobe,
            ef_search=ef_eff,
            quantizer_ef_search=quantizer_ef,
            use_gpu=bool(self.use_gpu and self.gpu_index is not None),
        )
        return _SearchPlan(
            queries=normalized,
            k=k_eff,
            search_k=search_k,
            params=params,
            timeline=current_timeline(),
        )

    def get_runtime_tuning(self) -> dict[str, object]:
        """Return the effective runtime tuning parameters and overrides.

        Returns
        -------
        dict[str, object]
            Dictionary with keys:
            - "active": dict with current effective parameters (nprobe, efSearch,
              quantizer_efSearch, k_factor)
            - "overrides": dict with runtime override parameters
            - "autotune_profile": dict with persisted autotune profile or empty dict
        """
        nprobe, ef_search, k_factor, quantizer = self._resolve_search_knobs(None)
        with self._tuning_lock:
            overrides = dict(self._runtime_overrides)
        profile = self._load_tuned_profile()
        return {
            "active": {
                "nprobe": nprobe,
                "efSearch": ef_search,
                "quantizer_efSearch": quantizer,
                "k_factor": k_factor,
            },
            "overrides": overrides,
            "autotune_profile": profile,
        }

    def apply_runtime_tuning(
        self,
        *,
        nprobe: int | None = None,
        ef_search: int | None = None,
        quantizer_ef_search: int | None = None,
        k_factor: float | None = None,
    ) -> dict[str, object]:
        """Apply runtime overrides (nprobe/efSearch/k_factor) to the active index.

        Parameters
        ----------
        nprobe : int | None, optional
            Override for IVF nprobe parameter. If None, uses current value.
        ef_search : int | None, optional
            Override for HNSW ef_search parameter. If None, uses current value.
        quantizer_ef_search : int | None, optional
            Override for IVF quantizer ef_search parameter. If None, uses current value.
        k_factor : float | None, optional
            Override for search k factor (multiplier for candidate retrieval).
            If None, uses current value.

        Returns
        -------
        dict[str, object]
            Updated runtime tuning dictionary (same format as `get_runtime_tuning()`).

        Raises
        ------
        ValueError
            If no tuning parameters are provided (all parameters are None).
        """
        sanitized = self._sanitize_runtime_overrides(
            nprobe=nprobe,
            ef_search=ef_search,
            quantizer_ef_search=quantizer_ef_search,
            k_factor=k_factor,
        )
        if not sanitized:
            msg = "No tuning parameters provided."
            raise ValueError(msg)
        with self._tuning_lock:
            self._runtime_overrides.update(sanitized)
        self._maybe_apply_runtime_parameters(sanitized)
        self._write_meta_snapshot(
            parameter_space=self._format_parameter_string(self._runtime_overrides)
        )
        return self.get_runtime_tuning()

    def reset_runtime_tuning(self) -> dict[str, object]:
        """Clear runtime overrides and revert to default (or autotuned) parameters.

        Returns
        -------
        dict[str, object]
            Updated runtime tuning dictionary with cleared overrides (same format
            as `get_runtime_tuning()`).
        """
        with self._tuning_lock:
            self._runtime_overrides.clear()
        self._maybe_apply_runtime_parameters(
            {
                "nprobe": self.default_nprobe,
                "efSearch": self.hnsw_ef_search,
            }
        )
        return self.get_runtime_tuning()

    def _search_primary(
        self, query: NDArrayF32, k: int, nprobe: int
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Search the primary index (adaptive type: Flat/IVFFlat/IVF-PQ).

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s), shape (n_queries, vec_dim) or (vec_dim,).
        k : int
            Number of nearest neighbors to return.
        nprobe : int
            Number of IVF cells to probe (for IVF indexes).

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (distances, ids) from primary index search.

        Notes
        -----
        Flat indexes (``IndexFlat*``) do not expose the ``nprobe`` attribute.
        The method checks for attribute support before assigning so that flat
        indexes skip the IVF-only parameter while IVF indexes continue to use
        ``nprobe`` for recall control.

        Raises
        ------
        RuntimeError
            If primary index is not available.
        """
        try:
            index = self._active_index()
        except RuntimeError as exc:
            msg = "Cannot search primary index: no FAISS index is available."
            raise RuntimeError(msg) from exc

        # Set nprobe (only affects IVF indexes)
        if hasattr(index, "nprobe"):
            index.nprobe = nprobe

        # Reshape query if needed
        if query.ndim == 1:
            query = query.reshape(1, -1)

        # Normalize query
        query_norm = query.copy().astype(np.float32)
        faiss.normalize_L2(query_norm)

        # Search primary index
        return index.search(query_norm, k)

    def _execute_dual_search(
        self,
        *,
        query: NDArrayF32,
        search_k: int,
        params: _SearchExecutionParams,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Run primary + optional secondary search with tracing.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s) of shape (n_queries, vec_dim) or (vec_dim,).
            Automatically normalized for cosine similarity.
        search_k : int
            Number of candidates to retrieve from each index before merging.
            Typically larger than final k to improve recall after merging.
        params : _SearchExecutionParams
            Runtime parameters describing IVF/HNSW traversal (nprobe, ef_search,
            quantizer efSearch) and whether GPU search is used.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Result set prior to top-k truncation. Distances and IDs from
            merged primary and secondary searches.

        Notes
        -----
        This is an internal method that orchestrates dual-index search with
        OpenTelemetry tracing. It applies runtime parameters, searches both
        indexes if secondary exists, merges results by score, and returns
        the combined candidate set. Time complexity: O(search_k * log n)
        for HNSW, O(nprobe * search_k) for IVF-family indexes.
        """
        with as_span("faiss.search", k=search_k, nprobe=params.nprobe, use_gpu=params.use_gpu):
            self._apply_runtime_parameters(
                nprobe=params.nprobe,
                ef_search=params.ef_search,
                quantizer_ef_search=params.quantizer_ef_search,
            )
            primary_dists, primary_ids = self._search_primary(query, search_k, params.nprobe)
            if self.secondary_index is None:
                return primary_dists, primary_ids
            secondary_dists, secondary_ids = self._search_secondary(query, search_k)
            merged_dists, merged_ids = self._merge_results(
                primary_dists,
                primary_ids,
                secondary_dists,
                secondary_ids,
                search_k,
            )
            LOGGER.debug(
                "Dual-index search completed",
                extra=_log_extra(
                    primary_results=primary_dists.shape[1],
                    secondary_results=secondary_dists.shape[1],
                    merged_results=merged_dists.shape[1],
                ),
            )
            return merged_dists, merged_ids

    def _maybe_refine_results(
        self,
        *,
        catalog: DuckDBCatalog | None,
        plan: _SearchPlan,
        identifiers: NDArrayI64,
    ) -> tuple[NDArrayF32, NDArrayI64] | None:
        """Optionally refine ANN candidates with exact similarity search.

        This method performs optional refinement of approximate nearest neighbor
        (ANN) search results by computing exact similarity scores using the original
        embeddings from the catalog. Refinement improves recall by reranking
        candidates based on exact inner product or cosine similarity rather than
        approximate distances from the FAISS index.

        Refinement is only performed when all conditions are met:
        - Catalog is available for embedding retrieval
        - Requested k is positive
        - Search k (with k_factor expansion) is greater than requested k
        - Refine k_factor is greater than 1.0

        Parameters
        ----------
        catalog : DuckDBCatalog | None
            DuckDB catalog instance providing embedding retrieval via
            get_embeddings_by_ids(). If None, refinement is skipped.
        plan : _SearchPlan
            Search plan containing normalized queries, effective k, search_k
            (with k_factor applied), and execution parameters. Used to determine
            refinement parameters and query vectors.
        identifiers : NDArrayI64
            Candidate chunk IDs from ANN search, shape (n_queries, search_k).
            These IDs are used to retrieve embeddings for exact similarity computation.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64] | None
            Tuple of (refined_scores, refined_ids) when refinement is performed
            and successful, both with shape (n_queries, k). Returns None when
            refinement is skipped (conditions not met), exact rerank is unavailable,
            or refinement fails (falls back to ANN ordering). Refined scores are
            exact similarity scores (inner product or cosine similarity); refined
            IDs are the top-k chunk identifiers after reranking.

        Notes
        -----
        This method uses exact_rerank() from codeintel_rev.retrieval.rerank_flat
        to compute exact similarities. Refinement is best-effort - if it fails,
        the method returns None and the caller falls back to ANN ordering. Time
        complexity: O(n_queries * search_k * vec_dim) for exact similarity computation
        plus O(n_queries * search_k * log(search_k)) for sorting. The method
        records metrics (FAISS_REFINE_KEPT_RATIO, FAISS_REFINE_LATENCY_SECONDS)
        for observability. Thread-safe if the catalog instance is thread-safe.
        """
        if catalog is None or plan.k <= 0 or plan.search_k <= plan.k or self.refine_k_factor <= 1.0:
            return None
        kept_ratio = plan.k / float(plan.search_k)
        FAISS_REFINE_KEPT_RATIO.observe(kept_ratio)
        refine_start = perf_counter()
        try:
            rerank_scores, rerank_ids = exact_rerank(
                catalog,
                plan.queries,
                identifiers[:, : plan.search_k],
                top_k=plan.k,
            )
        except (RuntimeError, ValueError) as exc:  # pragma: no cover - rerank is best-effort
            LOGGER.warning(
                "Exact rerank failed; falling back to ANN ordering",
                extra=_log_extra(error=str(exc)),
            )
            return None
        FAISS_REFINE_LATENCY_SECONDS.observe(max(perf_counter() - refine_start, 0.0))
        self._log_refine_delta(identifiers[:, : plan.k], rerank_ids)
        return rerank_scores, rerank_ids

    @staticmethod
    def _log_refine_delta(ann_ids: NDArrayI64, refined_ids: NDArrayI64) -> None:
        """Emit structured logs describing differences between ANN and refined hits."""
        if ann_ids.shape != refined_ids.shape:
            return
        overlaps: list[float] = []
        replacements: list[int] = []
        k = ann_ids.shape[1]
        for ann_row, ref_row in zip(ann_ids, refined_ids, strict=True):
            ann_set = {int(chunk_id) for chunk_id in ann_row if chunk_id >= 0}
            ref_set = {int(chunk_id) for chunk_id in ref_row if chunk_id >= 0}
            if not ann_set and not ref_set:
                continue
            overlap = len(ann_set & ref_set)
            overlaps.append(overlap / max(k, 1))
            replacements.append(max(len(ref_set) - overlap, 0))
        if not overlaps:
            return
        LOGGER.debug(
            "faiss.refine.delta",
            extra=_log_extra(
                avg_overlap=round(sum(overlaps) / len(overlaps), 4),
                avg_replacements=round(sum(replacements) / max(len(replacements), 1), 2),
                k=k,
            ),
        )

    def _search_secondary(self, query: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
        """Search the secondary index (flat, no training required).

        This method is public for testing and advanced use cases where
        separate primary/secondary search results are needed.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s), shape (n_queries, vec_dim) or (vec_dim,).
        k : int
            Number of nearest neighbors to return.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (distances, ids) from secondary index search.

        Raises
        ------
        RuntimeError
            If secondary index is not available (should not happen if called
            from search() after checking existence).
        """
        if self.secondary_index is None:
            msg = "Cannot search secondary index: secondary index not initialized."
            raise RuntimeError(msg)

        # Reshape query if needed
        if query.ndim == 1:
            query = query.reshape(1, -1)

        # Normalize query
        query_norm = query.copy().astype(np.float32)
        faiss.normalize_L2(query_norm)

        # Search secondary index (flat, no nprobe needed)
        return self.secondary_index.search(query_norm, k)

    def _primary_index_impl(self) -> _faiss.Index:
        """Return the underlying FAISS index implementation for primary CPU index.

        Returns
        -------
        _faiss.Index
            Downcast FAISS index representing the current primary structure.
        """
        cpu_index = self._require_cpu_index()
        base = getattr(cpu_index, "index", cpu_index)
        return self._downcast_index(base)

    @staticmethod
    def _merge_results(
        dists1: NDArrayF32,
        ids1: NDArrayI64,
        dists2: NDArrayF32,
        ids2: NDArrayI64,
        k: int,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Merge search results from two indexes by score.

        Combines results from primary and secondary indexes, sorts by distance
        (inner product, higher is better), and returns the top-k combined results.

        Parameters
        ----------
        dists1 : NDArrayF32
            Distances from first index, shape (n_queries, k1).
        ids1 : NDArrayI64
            IDs from first index, shape (n_queries, k1).
        dists2 : NDArrayF32
            Distances from second index, shape (n_queries, k2).
        ids2 : NDArrayI64
            IDs from second index, shape (n_queries, k2).
        k : int
            Number of top results to return after merging.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (merged_distances, merged_ids), both shape (n_queries, k).
            Results are sorted by distance (descending for inner product).

        Notes
        -----
        Uses inner product distance (cosine similarity after normalization),
        where higher values indicate better matches. Results are sorted in
        descending order and top-k is selected.
        """
        # Combine distances and IDs along the k dimension
        all_dists = np.concatenate([dists1, dists2], axis=1)
        all_ids = np.concatenate([ids1, ids2], axis=1)

        # Sort by distance (descending for inner product - higher is better)
        sorted_indices = np.argsort(-all_dists, axis=1)

        n_queries = all_dists.shape[0]
        filler = np.finfo(all_dists.dtype).min
        merged_dists = np.full((n_queries, k), filler, dtype=all_dists.dtype)
        merged_ids = np.full((n_queries, k), -1, dtype=all_ids.dtype)

        for query_idx in range(n_queries):
            seen: set[int] = set()
            out_pos = 0
            for candidate_idx in sorted_indices[query_idx]:
                candidate_id = int(all_ids[query_idx, candidate_idx])
                if candidate_id < 0 or candidate_id in seen:
                    continue
                seen.add(candidate_id)
                merged_dists[query_idx, out_pos] = all_dists[query_idx, candidate_idx]
                merged_ids[query_idx, out_pos] = candidate_id
                out_pos += 1
                if out_pos == k:
                    break

        return merged_dists, merged_ids

    def merge_indexes(self) -> None:
        """Merge secondary index into primary index (periodic rebuild).

        Rebuilds the primary index to include all vectors from both the primary
        and secondary indexes. After merging, the secondary index is cleared,
        allowing for a fresh start for future incremental updates.

        This operation is expensive (requires rebuilding the primary index) but
        should be performed periodically to maintain optimal search performance.
        After merging, search operations will only query the primary index,
        which is faster than dual-index search.

        The merge process:
        1. Extracts all vectors and IDs from both primary and secondary indexes
        2. Combines them into a single dataset
        3. Rebuilds the primary index with adaptive type selection
        4. Adds all vectors to the rebuilt primary index
        5. Clears the secondary index and incremental IDs

        Notes
        -----
        This method requires that vectors can be reconstructed from the indexes.
        For IVF-PQ indexes, reconstruction may be approximate (quantized).
        The method will raise RuntimeError if reconstruction is not supported.

        Examples
        --------
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=2560)
        >>> manager.build_index(initial_vectors)
        >>> manager.update_index(new_vectors, new_ids)  # Add incrementally
        >>> # Periodically merge to optimize performance
        >>> manager.merge_indexes()  # Rebuilds primary with all vectors

        Raises
        ------
        RuntimeError
            If the primary index is not available, or if vector extraction fails
            (e.g., index does not support reconstruction or ID mapping).
        """
        if self.secondary_index is None or len(self.incremental_ids) == 0:
            LOGGER.info(
                "No secondary index to merge - skipping merge operation",
                extra=_log_extra(secondary_size=len(self.incremental_ids)),
            )
            return

        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError as exc:
            msg = "Cannot merge indexes: primary index not available."
            raise RuntimeError(msg) from exc

        # Extract vectors from both indexes
        LOGGER.info(
            "Extracting vectors from primary and secondary indexes",
            extra=_log_extra(secondary_vectors=len(self.incremental_ids)),
        )
        primary_vectors, primary_ids = self._extract_all_vectors(cpu_index)
        secondary_vectors, secondary_ids = self._extract_all_vectors(self.secondary_index)

        # Combine vectors and IDs
        all_vectors = np.vstack([primary_vectors, secondary_vectors])
        all_ids = np.concatenate([primary_ids, secondary_ids])

        LOGGER.info(
            "Merging indexes",
            extra=_log_extra(
                primary_vectors=len(primary_ids),
                secondary_vectors=len(secondary_ids),
                total_vectors=len(all_ids),
            ),
        )

        # Rebuild primary index with combined dataset
        # Note: build_index normalizes vectors internally
        self.build_index(all_vectors)
        self.add_vectors(all_vectors, all_ids)

        # Clear secondary index
        self.secondary_index = None
        self.secondary_gpu_index = None
        self.incremental_ids.clear()

        LOGGER.info(
            "Successfully merged secondary vectors into primary index",
            extra=_log_extra(
                merged_secondary=len(secondary_ids),
                total_vectors=len(all_ids),
                primary_vectors=len(primary_ids),
            ),
        )

    def _extract_all_vectors(self, index: _faiss.Index) -> tuple[NDArrayF32, NDArrayI64]:
        """Extract all vectors and IDs from a FAISS index.

        Reconstructs vectors from the index and retrieves their associated IDs.
        For quantized indexes (e.g., IVF-PQ), reconstruction returns approximate
        vectors (dequantized from the codebook).

        Parameters
        ----------
        index : _faiss.Index
            FAISS index to extract vectors from. Must support `reconstruct()` and
            have an `id_map` attribute (IndexIDMap2 wrapper).

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
            This can occur with certain index types or if the index is not wrapped
            with IndexIDMap2.
        TypeError
            If the index's ``id_map`` interface is invalid (missing ``at`` or not callable),
            or if the id_map interface is missing required methods.
        """
        n_vectors = index.ntotal
        if n_vectors == 0:
            return np.empty((0, self.vec_dim), dtype=np.float32), np.empty(0, dtype=np.int64)

        _configure_direct_map(index)
        vectors = np.empty((n_vectors, self.vec_dim), dtype=np.float32)
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
                vectors[i] = base_index.reconstruct(i)
                ids[i] = stored_id
            except (AttributeError, RuntimeError) as exc:
                msg = f"Failed to extract vector at index {i}: {exc}"
                raise RuntimeError(msg) from exc

        return vectors, ids

    @staticmethod
    def _try_load_cuvs() -> None:
        """Load cuVS acceleration library if available.

        Raises
        ------
        ImportError
            If the optional pylibcuvs package is not installed.
        RuntimeError
            If the cuVS shared library cannot be loaded.
        """
        try:
            pylibcuvs = importlib.import_module("pylibcuvs")
        except ImportError as exc:  # pragma: no cover - optional dependency
            msg = "pylibcuvs is required for cuVS acceleration"
            raise ImportError(msg) from exc

        try:
            load_library = pylibcuvs.load_library
        except AttributeError as exc:  # pragma: no cover - unexpected signature
            msg = "pylibcuvs does not expose load_library()"
            raise RuntimeError(msg) from exc

        try:
            load_library()
        except OSError as exc:  # pragma: no cover - shared object load failures
            msg = "Failed to load cuVS shared libraries"
            raise RuntimeError(msg) from exc

    def _require_cpu_index(self) -> _faiss.Index:
        """Return the CPU index if initialized.

        Returns
        -------
        _faiss.Index
            Initialized CPU FAISS index.

        Raises
        ------
        RuntimeError
            If the index has not been built or loaded yet.
        """
        if self.cpu_index is None:
            msg = "Index not built"
            raise RuntimeError(msg)
        return self.cpu_index

    def require_cpu_index(self) -> _faiss.Index:
        """Return the CPU FAISS index via the public interface.

        Returns
        -------
        _faiss.Index
            Initialized CPU FAISS index.
        """
        return self._require_cpu_index()

    # ---------------------------------------------------------------------
    # Modern helper utilities (factory management, tuning, telemetry)
    # ---------------------------------------------------------------------

    @staticmethod
    def get_compile_options() -> str:
        """Return FAISS compile options for readiness logs.

        Returns
        -------
        str
            Human-readable compile option string or ``"unknown"``.
        """
        get_opts = getattr(faiss, "get_compile_options", None)
        options = "unknown"
        if callable(get_opts):
            options = str(get_opts())
        set_compile_flags_id(options)
        return options

    def _search_with_params(
        self,
        query: NDArrayF32,
        k: int,
        *,
        param_str: str | None = None,
        refine_k_factor: float | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Direct search utility that applies ParameterSpace overrides ad-hoc.

        Parameters
        ----------
        query : NDArrayF32
            Query vector(s) of shape (n_queries, vec_dim) or (vec_dim,).
            Automatically normalized for cosine similarity.
        k : int
            Number of nearest neighbors to return per query.
        param_str : str | None, optional
            FAISS ParameterSpace parameter string (e.g., "nprobe=64,ef_search=128").
            Applied directly to the index before search. If None, uses index defaults.
        refine_k_factor : float | None, optional
            If > 1.0, refines results by running exact search over primary index
            with k * refine_k_factor candidates. Improves recall at cost of latency.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Distances/IDs pair for the provided query batch. Distances are cosine
            similarity scores; IDs are chunk identifiers.

        Notes
        -----
        This method bypasses the dual-index search path and applies FAISS
        ParameterSpace settings directly. Useful for ad-hoc tuning experiments.
        Time complexity depends on index type and param_str settings.
        """
        xq = self._ensure_2d(query)
        faiss.normalize_L2(xq)
        index = self._active_index()
        if param_str:
            try:
                faiss.ParameterSpace().set_index_parameters(index, param_str)
            except (RuntimeError, ValueError) as exc:
                LOGGER.warning(
                    "Failed to apply FAISS parameters",
                    extra=_log_extra(param_str=param_str, error=str(exc)),
                )
        distances, ids = index.search(xq, k)
        if refine_k_factor and refine_k_factor > 1.0:
            distances, ids = self._refine_with_flat(xq, ids, k)
        return distances, ids

    def autotune(
        self,
        queries: NDArrayF32,
        truths: NDArrayF32,
        *,
        k: int = 10,
        sweep: Sequence[str] | None = None,
    ) -> Mapping[str, Any]:
        """Sweep FAISS ParameterSpace settings and persist the best profile.

        Parameters
        ----------
        queries : NDArrayF32
            Query vectors of shape (n_queries, vec_dim) for evaluation.
            Automatically normalized for cosine similarity.
        truths : NDArrayF32
            Ground truth vectors of shape (n_truths, vec_dim) used to compute
            recall. Automatically normalized for cosine similarity.
        k : int, optional
            Number of nearest neighbors to retrieve during evaluation (default: 10).
        sweep : Sequence[str] | None, optional
            List of ParameterSpace parameter strings to evaluate (e.g.,
            ["nprobe=16", "nprobe=32", "nprobe=64"]). If None, uses default
            sweep over nprobe values [16, 32, 64, 96, 128].

        Returns
        -------
        Mapping[str, Any]
            Summary dictionary with keys:
            - "recall_at_k": float, best recall achieved
            - "latency_ms": float, latency in milliseconds for best config
            - "param_str": str, ParameterSpace string for best config
            - Additional keys parsed from param_str (e.g., "nprobe", "ef_search")

        Notes
        -----
        This method performs brute-force ground truth computation, then evaluates
        each parameter combination in the sweep. The best configuration (highest
        recall, breaking ties by lowest latency) is persisted to
        `autotune_profile_path` and stored in `_tuned_parameters` for future use.
        Time complexity: O(n_queries * n_truths) for ground truth + O(len(sweep) * search_time).
        """
        xq = self._ensure_2d(queries).astype(np.float32)
        xt = self._ensure_2d(truths).astype(np.float32)
        faiss.normalize_L2(xq)
        faiss.normalize_L2(xt)
        sweep = sweep or ["nprobe=16", "nprobe=32", "nprobe=64", "nprobe=96", "nprobe=128"]
        truth_ids = self._brute_force_truth_ids(xq, xt, min(k, xt.shape[0]))
        best_recall = 0.0
        best_latency = float("inf")
        best_param = ""
        for spec in sweep:
            latency_ms, (_, ids) = self._timed_search_with_params(xq, k, spec)
            recall = self._estimate_recall(ids, truth_ids)
            is_better = recall > best_recall or (
                math.isclose(recall, best_recall) and latency_ms < best_latency
            )
            if is_better:
                best_recall = float(recall)
                best_latency = float(latency_ms)
                best_param = spec
        if not best_param:
            return {
                "recall_at_k": best_recall,
                "latency_ms": best_latency,
                "param_str": best_param,
            }
        profile: dict[str, float | str] = {
            "recall_at_k": best_recall,
            "latency_ms": best_latency,
            "param_str": best_param,
        }
        for token in best_param.split(","):
            if "=" not in token:
                continue
            key, raw_value = token.split("=", 1)
            try:
                profile[key.strip()] = float(raw_value)
            except ValueError:
                continue
        try:
            self.autotune_profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.autotune_profile_path.write_text(json.dumps(profile, indent=2))
        except OSError as exc:
            LOGGER.warning(
                "Failed to persist FAISS autotune profile",
                extra=_log_extra(path=str(self.autotune_profile_path), error=str(exc)),
            )
        self._tuned_parameters = profile
        return profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_adaptive_index(
        self, vectors: NDArrayF32, n_vectors: int
    ) -> tuple[_faiss.Index, str]:
        """Construct an index structure using heuristics for corpus size.

        Parameters
        ----------
        vectors : NDArrayF32
            Training vectors of shape (n_vectors, vec_dim). Must match
            `self.vec_dim`. Automatically normalized for cosine similarity.
        n_vectors : int
            Number of vectors in the corpus. Used to select index type:
            - < 5K: Flat (exact search)
            - 5K-50K: IVFFlat (approximate, fast training)
            - > 50K: IVF-PQ (approximate, compressed)

        Returns
        -------
        tuple[_faiss.Index, str]
            Trained FAISS index and a descriptive factory label ("Flat", "IVFFlat",
            or "IVFPQ"). The index is ready for search after training completes.

        Notes
        -----
        This method implements adaptive index selection based on corpus size to
        balance search speed, recall, and memory usage. Small corpora use exact
        search (Flat), medium corpora use IVFFlat for fast approximate search,
        and large corpora use IVF-PQ for memory-efficient approximate search.
        Training time: O(n_vectors) for Flat, O(n_vectors * log(nlist)) for IVF-family.
        """
        if n_vectors < _SMALL_CORPUS_THRESHOLD:
            LOGGER.info(
                "Using IndexFlatIP for small corpus",
                extra=_log_extra(n_vectors=n_vectors, index_type="flat"),
            )
            return faiss.IndexFlatIP(self.vec_dim), "Flat"
        if n_vectors < _MEDIUM_CORPUS_THRESHOLD:
            nlist = self._dynamic_nlist(n_vectors, minimum=100)
            quantizer = faiss.IndexFlatIP(self.vec_dim)
            cpu_index = faiss.IndexIVFFlat(
                quantizer,
                self.vec_dim,
                nlist,
                faiss.METRIC_INNER_PRODUCT,
            )
            cpu_index.train(vectors)
            LOGGER.info(
                "Using IVFFlat for medium corpus",
                extra=_log_extra(n_vectors=n_vectors, nlist=nlist, index_type="ivf_flat"),
            )
            return cpu_index, f"IVF{nlist},Flat"
        nlist = self._dynamic_nlist(n_vectors, minimum=1024)
        index_string = f"OPQ64,IVF{nlist},PQ64"
        cpu_index = faiss.index_factory(self.vec_dim, index_string, faiss.METRIC_INNER_PRODUCT)
        cpu_index.train(vectors)
        LOGGER.info(
            "Using IVF-PQ for large corpus",
            extra=_log_extra(n_vectors=n_vectors, nlist=nlist, index_type="ivf_pq"),
        )
        return cpu_index, index_string

    def _dynamic_nlist(self, n_vectors: int, *, minimum: int) -> int:
        if self.faiss_family != "auto":
            return max(self.nlist, minimum)
        approx = max(int(np.sqrt(n_vectors)), minimum)
        return max(approx, minimum)

    def _factory_string_for(self, family: str, _n_vectors: int) -> str:
        fam = family.lower()
        resolved_nlist = max(self.nlist, 1)
        if fam == "flat":
            return "Flat"
        if fam == "ivf_flat":
            return f"IVF{resolved_nlist},Flat"
        if fam == "ivf_pq":
            opq = f"OPQ{self.opq_m}," if self.opq_m > 0 else ""
            return f"{opq}IVF{resolved_nlist},PQ{self.pq_m}x{self.pq_nbits}"
        if fam == "ivf_pq_refine":
            opq = f"OPQ{self.opq_m}," if self.opq_m > 0 else ""
            return f"{opq}IVF{resolved_nlist},PQ{self.pq_m}x{self.pq_nbits},Refine(Flat)"
        if fam == "hnsw":
            return f"HNSW{self.hnsw_m}"
        return "Flat"

    def _record_factory_choice(
        self,
        index: _faiss.Index,
        label: str | None = None,
        parameter_space: str | None = None,
        vector_count: int | None = None,
    ) -> None:
        try:
            name = label or type(self._downcast_index(index)).__name__
        except (AttributeError, RuntimeError):
            name = label or type(index).__name__
        extra = _log_extra(index_type=name, vec_dim=self.vec_dim, nlist=self.nlist)
        LOGGER.info("FAISS index configured", extra=extra)
        set_factory_id(name)
        effective_count = index.ntotal if vector_count is None else int(vector_count)
        self._write_meta_snapshot(
            factory=name,
            vector_count=effective_count,
            parameter_space=parameter_space,
        )

    def _apply_runtime_parameters(
        self,
        *,
        nprobe: int | None,
        ef_search: int | None,
        quantizer_ef_search: int | None = None,
    ) -> None:
        """Apply runtime search knobs to the active FAISS index."""
        params: list[str] = []
        if nprobe is not None:
            params.append(f"nprobe={int(nprobe)}")
        if ef_search is not None:
            params.append(f"efSearch={int(ef_search)}")
        if quantizer_ef_search is not None:
            params.append(f"quantizer_efSearch={int(quantizer_ef_search)}")
        if not params:
            return
        index = self._active_index()
        try:
            faiss.ParameterSpace().set_index_parameters(index, ",".join(params))
        except (RuntimeError, AttributeError, ValueError):
            if nprobe is not None and hasattr(index, "nprobe"):
                index.nprobe = int(nprobe)

    def _maybe_apply_runtime_parameters(self, overrides: Mapping[str, float | int]) -> None:
        """Best-effort application of overrides to the live index if available."""
        if not overrides:
            return
        try:
            self._apply_runtime_parameters(
                nprobe=int(overrides["nprobe"]) if "nprobe" in overrides else None,
                ef_search=int(overrides["efSearch"]) if "efSearch" in overrides else None,
                quantizer_ef_search=(
                    int(overrides["quantizer_efSearch"])
                    if "quantizer_efSearch" in overrides
                    else None
                ),
            )
        except RuntimeError as exc:
            LOGGER.debug(
                "Unable to apply FAISS runtime overrides immediately",
                extra=_log_extra(reason=str(exc)),
            )

    @staticmethod
    def _sanitize_runtime_overrides(
        *,
        nprobe: int | None,
        ef_search: int | None,
        quantizer_ef_search: int | None,
        k_factor: float | None,
    ) -> dict[str, float]:
        sanitized: dict[str, float] = {}
        if nprobe is not None:
            nprobe_int = int(nprobe)
            if nprobe_int <= 0:
                msg = f"nprobe must be positive, got {nprobe_int}"
                raise ValueError(msg)
            sanitized["nprobe"] = nprobe_int
        if ef_search is not None:
            ef_int = int(ef_search)
            if ef_int <= 0:
                msg = f"efSearch must be positive, got {ef_int}"
                raise ValueError(msg)
            sanitized["efSearch"] = ef_int
        if quantizer_ef_search is not None:
            q_int = int(quantizer_ef_search)
            if q_int <= 0:
                msg = f"quantizer_efSearch must be positive, got {q_int}"
                raise ValueError(msg)
            sanitized["quantizer_efSearch"] = q_int
        if k_factor is not None:
            kf_val = float(k_factor)
            if kf_val < 1.0:
                msg = f"k_factor must be >= 1.0, got {kf_val}"
                raise ValueError(msg)
            sanitized["k_factor"] = kf_val
        return sanitized

    def set_search_parameters(self, param_str: str) -> dict[str, object]:
        """Apply FAISS ParameterSpace string and persist overrides.

        Parameters
        ----------
        param_str : str
            Comma-separated FAISS ParameterSpace string
            (e.g., ``"nprobe=64,efSearch=128"``).

        Returns
        -------
        dict[str, object]
            Runtime tuning snapshot as returned by :meth:`get_runtime_tuning`.

        Raises
        ------
        ValueError
            If the parameter string is invalid or FAISS rejects the override.
        """
        faiss_spec, sanitized = self._prepare_parameter_string(param_str)
        if faiss_spec:
            try:
                faiss.ParameterSpace().set_index_parameters(self._active_index(), faiss_spec)
            except (AttributeError, RuntimeError, ValueError) as exc:
                msg = f"Unable to apply FAISS parameters: {faiss_spec}"
                raise ValueError(msg) from exc
        with self._tuning_lock:
            self._runtime_overrides.update(sanitized)
        self._write_meta_snapshot(
            parameter_space=self._format_parameter_string(self._runtime_overrides)
        )
        return self.get_runtime_tuning()

    def _prepare_parameter_string(self, param_str: str) -> tuple[str | None, dict[str, float]]:
        if not param_str or not param_str.strip():
            msg = "Parameter string must be non-empty."
            raise ValueError(msg)
        faiss_pairs: list[str] = []
        int_params: dict[str, int] = {}
        k_factor_value: float | None = None
        for chunk in param_str.split(","):
            key, sep, raw_value = chunk.partition("=")
            key = key.strip()
            value = raw_value.strip()
            if not key or not sep or not value:
                msg = f"Invalid parameter fragment: '{chunk}'"
                raise ValueError(msg)
            try:
                numeric_value = float(value)
            except ValueError as exc:
                msg = f"Parameter '{key}' value '{value}' is not numeric"
                raise ValueError(msg) from exc
            if key == "k_factor":
                k_factor_value = numeric_value
                continue
            if key not in {"nprobe", "efSearch", "quantizer_efSearch"}:
                msg = f"Unsupported FAISS parameter '{key}'"
                raise ValueError(msg)
            int_params[key] = int(numeric_value)
            faiss_pairs.append(f"{key}={value}")
        sanitized = self._sanitize_runtime_overrides(
            nprobe=int_params.get("nprobe"),
            ef_search=int_params.get("efSearch"),
            quantizer_ef_search=int_params.get("quantizer_efSearch"),
            k_factor=k_factor_value,
        )
        if not sanitized:
            msg = "Parameter string must include at least one supported override."
            raise ValueError(msg)
        return (",".join(faiss_pairs) if faiss_pairs else None, sanitized)

    @staticmethod
    def _format_parameter_string(overrides: Mapping[str, float]) -> str | None:
        ordered: list[str] = []
        for key in ("nprobe", "efSearch", "quantizer_efSearch", "k_factor"):
            if key not in overrides:
                continue
            value = overrides[key]
            if key == "k_factor":
                ordered.append(f"{key}={value}")
            else:
                ordered.append(f"{key}={int(value)}")
        return ",".join(ordered) if ordered else None

    def _meta_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object]
        if self._meta_path.exists():
            try:
                snapshot = json.loads(self._meta_path.read_text())
            except json.JSONDecodeError:
                snapshot = {}
        else:
            snapshot = {}
        snapshot.update(
            {
                "index_path": str(self.index_path),
                "vec_dim": self.vec_dim,
                "faiss_family": self.faiss_family,
                "default_parameters": {
                    "nprobe": self.default_nprobe,
                    "efSearch": self.hnsw_ef_search,
                    "quantizer_efSearch": None,
                    "k_factor": self.refine_k_factor,
                },
            }
        )
        return snapshot

    def _write_meta_snapshot(
        self,
        *,
        factory: str | None = None,
        vector_count: int | None = None,
        parameter_space: str | None = None,
    ) -> None:
        meta = self._meta_snapshot()
        if factory is not None:
            meta["factory"] = factory
        if vector_count is not None:
            meta["vector_count"] = int(vector_count)
        if parameter_space is not None:
            meta["parameter_space"] = parameter_space
        meta["runtime_overrides"] = dict(self._runtime_overrides)
        meta["compile_options"] = self.get_compile_options()
        meta["updated_at"] = datetime.now(UTC).isoformat()
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    def _resolve_search_knobs(
        self,
        override_nprobe: int | None,
        *,
        override_ef: int | None = None,
        override_k_factor: float | None = None,
        override_quantizer: int | None = None,
    ) -> tuple[int | None, int | None, float, int | None]:
        profile = self._load_tuned_profile()
        with self._tuning_lock:
            overrides = dict(self._runtime_overrides)

        # runtime overrides stored using camelCase for FAISS parity
        def _lookup_override(key: str, snake_key: str | None = None) -> float | int | None:
            if key in overrides:
                return overrides[key]
            if snake_key and snake_key in overrides:
                return overrides[snake_key]
            return None

        def _pick(
            override_value: float | None,
            *,
            runtime_key: str,
            snake_key: str | None,
            profile_key: str,
            default: float | None,
        ) -> float | int | None:
            if override_value is not None:
                return override_value
            candidate = _lookup_override(runtime_key, snake_key)
            if candidate is not None:
                return candidate
            if profile:
                prof_val = profile.get(profile_key)
                if isinstance(prof_val, (int, float)):
                    return prof_val
            return default

        nprobe_source = _pick(
            override_nprobe,
            runtime_key="nprobe",
            snake_key=None,
            profile_key="nprobe",
            default=self.default_nprobe,
        )
        ef_candidate = _pick(
            override_ef,
            runtime_key="efSearch",
            snake_key="ef_search",
            profile_key="efSearch",
            default=self.hnsw_ef_search,
        )
        kf_candidate = _pick(
            override_k_factor,
            runtime_key="k_factor",
            snake_key="k_factor",
            profile_key="k_factor",
            default=self.refine_k_factor,
        )
        quantizer_candidate = _pick(
            override_quantizer,
            runtime_key="quantizer_efSearch",
            snake_key="quantizer_ef_search",
            profile_key="quantizer_efSearch",
            default=None,
        )
        nprobe_eff = int(nprobe_source) if nprobe_source is not None else None
        ef_eff = int(ef_candidate) if ef_candidate is not None else None
        k_factor = float(kf_candidate) if kf_candidate is not None else self.refine_k_factor
        quantizer_ef = int(quantizer_candidate) if quantizer_candidate is not None else None
        return nprobe_eff, ef_eff, k_factor, quantizer_ef

    def _load_tuned_profile(self) -> dict[str, float | str]:
        if self._tuned_parameters is not None:
            return self._tuned_parameters
        profile_path = self._profile_path_for_read()
        if profile_path is None:
            return {}
        try:
            raw = profile_path.read_text()
        except OSError as exc:
            LOGGER.warning(
                "Failed to load FAISS autotune profile",
                extra=_log_extra(path=str(profile_path), error=str(exc)),
            )
            return {}
        try:
            profile = cast("dict[str, float | str]", json.loads(raw))
        except json.JSONDecodeError as exc:
            LOGGER.warning(
                "Failed to parse FAISS autotune profile",
                extra=_log_extra(path=str(profile_path), error=str(exc)),
            )
            return {}
        self._tuned_parameters = profile
        return profile

    def _profile_path_for_read(self) -> Path | None:
        if self.autotune_profile_path.exists():
            return self.autotune_profile_path
        if self._legacy_autotune_profile_path.exists():
            return self._legacy_autotune_profile_path
        return None

    def _timed_search_with_params(
        self, queries: NDArrayF32, k: int, param_str: str
    ) -> tuple[float, tuple[NDArrayF32, NDArrayI64]]:
        start = perf_counter()
        result = self._search_with_params(queries, k, param_str=param_str)
        elapsed = (perf_counter() - start) * 1000.0
        return elapsed, result

    @staticmethod
    def _brute_force_truth_ids(queries: NDArrayF32, truths: NDArrayF32, k: int) -> NDArrayI64:
        sims = queries @ truths.T
        k = min(k, sims.shape[1])
        if k <= 0:
            return np.empty((queries.shape[0], 0), dtype=np.int64)
        idx = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
        return idx.astype(np.int64)

    @staticmethod
    def _estimate_recall(candidates: NDArrayI64, truth: NDArrayI64) -> float:
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

    @staticmethod
    def _ensure_2d(array: NDArrayF32) -> NDArrayF32:
        arr = np.asarray(array, dtype=np.float32)
        if arr.ndim == 1:
            return arr.reshape(1, -1)
        return arr

    def _refine_with_flat(
        self, queries: NDArrayF32, _candidate_ids: NDArrayI64, k: int
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Refine candidates by running an exact search over the primary index.

        Parameters
        ----------
        queries : NDArrayF32
            Query vector(s) of shape (n_queries, vec_dim) or (vec_dim,).
            Automatically normalized for cosine similarity.
        _candidate_ids : NDArrayI64
            Candidate IDs from initial approximate search (unused, kept for
            API compatibility). The method performs a fresh exact search instead.
        k : int
            Number of nearest neighbors to return per query.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Distances and IDs computed via exact search over the primary index.
            Distances are cosine similarity scores; IDs are chunk identifiers.

        Notes
        -----
        This method performs exact (Flat) search over the primary index to refine
        results from approximate search. Improves recall at the cost of higher
        latency. Time complexity: O(n_vectors * k) for Flat index.
        """
        return self._search_primary(queries, k, self.default_nprobe)

    @staticmethod
    def _downcast_index(index: _faiss.Index) -> _faiss.Index:
        """Return a concrete FAISS index implementation when possible.

        Parameters
        ----------
        index : _faiss.Index
            FAISS index handle, which may be a base Index type or wrapper.

        Returns
        -------
        _faiss.Index
            Downcast index when supported (e.g., IndexIVFFlat from Index),
            otherwise the provided handle unchanged.

        Notes
        -----
        This helper uses `faiss.downcast_index()` to extract concrete index
        implementations from wrapper types. Useful for accessing index-specific
        attributes (e.g., `nprobe` on IVF indexes). No-op if downcast is not
        supported or index is already concrete.
        """
        try:
            return faiss.downcast_index(index)
        except (AttributeError, RuntimeError):
            return index

    def _active_index(self) -> _faiss.Index:
        """Return the best available search index.

        Returns
        -------
        _faiss.Index
            GPU-backed index when available, otherwise the CPU index.

        Raises
        ------
        RuntimeError
            If neither CPU nor GPU indexes are available.
        """
        if self.gpu_index is not None:
            return self.gpu_index
        if self.cpu_index is not None:
            return self.cpu_index
        msg = "No index available"
        raise RuntimeError(msg)


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


def _configure_direct_map(index: _faiss.Index) -> None:
    """Ensure FAISS direct maps are array-backed for reconstruction."""
    _set_direct_map_type(index)
    base_index = getattr(index, "index", None)
    if base_index is not None:
        _set_direct_map_type(base_index)


def _set_direct_map_type(index: _faiss.Index) -> None:
    """Enable direct map support on FAISS indexes when available."""
    try:
        concrete = faiss.downcast_index(index)
    except (AttributeError, RuntimeError):
        concrete = index
    make_direct_map = getattr(concrete, "make_direct_map", None)
    if callable(make_direct_map):
        try:
            make_direct_map()
        except (AttributeError, RuntimeError) as exc:
            LOGGER.debug(
                "FAISS make_direct_map failed",
                extra=_log_extra(index_type=type(index).__name__, error=str(exc)),
            )


__all__ = ["FAISSManager"]
