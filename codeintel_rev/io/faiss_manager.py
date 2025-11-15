"""FAISS manager for GPU-accelerated vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with cuVS acceleration,
CPU persistence, and GPU cloning. Index type is automatically selected based on
corpus size for optimal performance.
"""

# ruff: noqa: SLF001

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from pathlib import Path
from threading import RLock
from time import perf_counter
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.errors import VectorIndexIncompatibleError, VectorIndexStateError
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.metrics.registry import (
    FAISS_ANN_LATENCY_SECONDS,
    FAISS_BUILD_SECONDS_LAST,
    FAISS_BUILD_TOTAL,
    FAISS_INDEX_CODE_SIZE_BYTES,
    FAISS_INDEX_CUVS_ENABLED,
    FAISS_INDEX_DIM,
    FAISS_INDEX_GPU_ENABLED,
    FAISS_INDEX_SIZE_VECTORS,
    FAISS_POSTFILTER_DENSITY,
    FAISS_REFINE_KEPT_RATIO,
    FAISS_REFINE_LATENCY_SECONDS,
    FAISS_SEARCH_ERRORS_TOTAL,
    FAISS_SEARCH_LAST_K,
    FAISS_SEARCH_LAST_MS,
    FAISS_SEARCH_LATENCY_SECONDS,
    FAISS_SEARCH_NPROBE,
    FAISS_SEARCH_TOTAL,
    HNSW_SEARCH_EF,
    set_compile_flags_id,
    set_factory_id,
)
from codeintel_rev.observability.execution_ledger import step as ledger_step
from codeintel_rev.observability.otel import record_span_event
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.retrieval.rerank_flat import FlatReranker
from codeintel_rev.retrieval.types import SearchHit
from codeintel_rev.telemetry.decorators import span_context
from codeintel_rev.telemetry.steps import StepEvent, emit_step
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import
from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    import faiss as _faiss
    import numpy as np

    FaissIndex = _faiss.Index
else:
    np = cast("Any", LazyModule("numpy", "FAISS manager vector operations"))
    FaissIndex = object

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


def apply_parameters(index: FaissIndex, param_str: str) -> None:
    """Apply a FAISS ParameterSpace string to ``index``.

    This function applies runtime tuning parameters to a FAISS index using the
    ParameterSpace API. The parameter string specifies index-specific tuning
    knobs (e.g., nprobe for IVF indices, efSearch for HNSW indices) that control
    search behavior and performance. The parameters are applied in-place to the
    index object, modifying its runtime behavior for subsequent search operations.

    Parameters
    ----------
    index : FaissIndex
        FAISS index object to apply parameters to. Must support the ParameterSpace
        API (typically IVF, HNSW, or other tunable index types). The index is
        modified in-place with the new parameter values.
    param_str : str
        Parameter string specifying tuning parameters in FAISS ParameterSpace format
        (e.g., "nprobe=32,efSearch=64"). Must be non-empty and contain valid
        parameter specifications for the index type.

    Raises
    ------
    ValueError
        Raised in the following cases:
        - ``param_str`` is empty or whitespace-only: parameter string must be
          non-empty to apply valid tuning parameters
        - Parameter application fails: FAISS ParameterSpace API raises
          AttributeError, RuntimeError, or ValueError when the parameter string
          is invalid, incompatible with the index type, or contains unsupported
          parameters

    Notes
    -----
    This function wraps the FAISS ParameterSpace API to provide a convenient
    interface for applying runtime tuning parameters. The function validates input
    and provides clear error messages when parameter application fails. Time
    complexity: O(1) for parameter parsing and application. The function modifies
    the index object in-place and is not thread-safe if the index is being used
    concurrently. Parameters persist for the lifetime of the index object.
    """
    if not param_str or not param_str.strip():
        msg = "Parameter string must be non-empty."
        raise ValueError(msg)
    try:
        faiss.ParameterSpace().set_index_parameters(index, param_str)
    except (AttributeError, RuntimeError, ValueError) as exc:
        msg = f"Unable to apply FAISS parameters: {param_str}"
        raise ValueError(msg) from exc


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
class RefineSearchConfig:
    """Configuration bundle for refine searches."""

    nprobe: int | None = None
    runtime: SearchRuntimeOverrides | None = None
    source: str = "faiss"


@dataclass(frozen=True, slots=True)
class _TuningOverrides:
    """Normalized tuning overrides extracted from a profile payload."""

    param_str: str
    nprobe: int | None
    ef_search: int | None
    quantizer_ef_search: int | None
    k_factor: float | None


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
        index_label = self.index_path.name or self.index_path.stem or str(self.index_path)
        exported_at = datetime.now(UTC)
        table = pa.Table.from_arrays(
            [
                pa.array(rows),
                pa.array(idmap),
                pa.array([index_label] * len(rows)),
                pa.array(
                    [exported_at] * len(rows),
                    type=pa.timestamp("ns", tz="UTC"),
                ),
            ],
            names=["faiss_row", "external_id", "index_name", "ts"],
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out_path, compression="snappy", use_dictionary=True)
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
    _FAISSIdMapMixin
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
    if it doesn't exist.     Use `merge_indexes()` periodically to merge secondary
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
        vec_dim: int = 3584,
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
        self.faiss_family: str | None = opts.faiss_family
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

    def _write_profile(self, path: Path) -> None:
        """Persist a minimal profile snapshot describing the active CPU index."""
        cpu_index = self.cpu_index
        if cpu_index is None:
            return
        profile = {
            "dims": int(cpu_index.d),
            "ntotal": int(cpu_index.ntotal),
            "is_trained": bool(getattr(cpu_index, "is_trained", False)),
            "type_name": type(cpu_index).__name__,
            "faiss_family": self.faiss_family,
            "refine_k_factor": self.refine_k_factor,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
        LOGGER.debug("Persisted FAISS profile snapshot", extra=_log_extra(path=str(path)))

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
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=3584)
        >>> vectors = np.random.randn(1000, 3584).astype(np.float32)
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
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=3584)
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
        """Ensure the secondary flat index exists, creating it if necessary.

        This method lazily initializes the secondary index used for fast incremental
        updates. The secondary index is a flat (IndexFlatIP) index wrapped with
        IndexIDMap2 for ID management. It requires no training and enables instant
        vector additions without rebuilding the primary index.

        The secondary index is created only once per manager instance. Subsequent
        calls to this method are no-ops if the index already exists. The index is
        configured with direct map support to enable vector reconstruction.

        Notes
        -----
        The secondary index uses IndexFlatIP (inner product) for exact search over
        newly added vectors. This provides fast incremental updates at the cost of
        linear search time. The index is automatically searched alongside the primary
        index during dual-index search operations. Time complexity: O(1) if index
        exists, O(1) for creation (no training required). The method performs no I/O
        operations and is idempotent.
        """
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
        """Build a function to check if chunk IDs exist in the primary index.

        This method constructs a callable that checks whether a given chunk ID exists
        in the primary FAISS index. It attempts multiple strategies in order of
        efficiency: (1) use native contains() method if available, (2) use search()
        or find() methods that return index positions, (3) fall back to building a
        set of all existing IDs for O(1) lookup. The method handles cases where the
        index is unavailable or lacks ID mapping support.

        Returns
        -------
        Callable[[int], bool]
            Function that accepts a chunk ID (int) and returns True if the ID exists
            in the primary index, False otherwise. The function is optimized for the
            available FAISS ID map interface. Returns a no-op function (always False)
            if the primary index is unavailable or lacks ID mapping support.

        Notes
        -----
        This method is used by update_index() to filter out duplicate IDs before
        adding vectors to the secondary index. The returned function is thread-safe
        if the underlying FAISS index is thread-safe. Time complexity of the returned
        function depends on the strategy: O(1) for native contains() or set lookup,
        O(log n) for search-based methods. The method itself is O(1) if native
        methods are available, O(n) if building an ID set is required.
        """
        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError:
            return lambda _id: False

        id_map_obj = getattr(cpu_index, "id_map", None)
        if id_map_obj is None:
            return lambda _id: False

        for attr, builder in (
            ("contains", _wrap_bool_contains),
            ("search", _wrap_index_contains),
            ("find", _wrap_index_contains),
        ):
            raw = getattr(id_map_obj, attr, None)
            if callable(raw):
                return builder(cast("Callable[[int], object]", raw))

        existing_ids = self._build_existing_ids_set(cpu_index, id_map_obj)
        return lambda id_val: int(id_val) in existing_ids

    @staticmethod
    def _build_existing_ids_set(cpu_index: _faiss.Index, id_map_obj: object) -> set[int]:
        """Build a set of all existing chunk IDs from the FAISS index.

        This helper method extracts all chunk IDs stored in the FAISS index by
        iterating through the ID map and collecting external IDs. It uses the
        id_map.at() method to retrieve the external ID for each internal index
        position. This set is used as a fallback for duplicate checking when
        native contains() methods are unavailable.

        Parameters
        ----------
        cpu_index : _faiss.Index
            FAISS CPU index to extract IDs from. Must have an ntotal attribute
            indicating the number of vectors in the index.
        id_map_obj : object
            ID map object from the FAISS index (typically from index.id_map).
            Must expose an at() method that accepts an index position and returns
            the external chunk ID.

        Returns
        -------
        set[int]
            Set containing all external chunk IDs stored in the index. Returns an
            empty set if the index has no vectors, lacks ID mapping support, or
            if extraction fails (e.g., missing at() method, type errors).

        Notes
        -----
        This method is used as a fallback strategy when native contains() methods
        are unavailable. Building the set requires O(n) time and O(n) space where
        n is the number of vectors. The set enables O(1) ID lookups for duplicate
        checking. The method handles errors gracefully, returning an empty set
        when extraction is not possible.
        """
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
        """Collect indices of unique IDs that should be added to the secondary index.

        This method filters the input ID array to identify which IDs are truly new
        and should be added to the secondary index. An ID is considered unique if
        it (1) appears only once in the current batch (no duplicates within batch),
        (2) is not already in the secondary index (not in incremental_ids), and
        (3) is not already in the primary index (checked via primary_contains).

        Parameters
        ----------
        new_ids : NDArrayI64
            Array of chunk IDs to check for uniqueness, shape (n,) or (n, 1).
            The array is flattened before processing. IDs are converted to integers
            for comparison.
        primary_contains : Callable[[int], bool]
            Function that checks if a chunk ID exists in the primary index. Returns
            True if the ID exists, False otherwise. Used to filter out IDs that are
            already indexed in the primary index.

        Returns
        -------
        list[int]
            List of array indices (offsets) corresponding to unique IDs that should
            be added to the secondary index. The indices can be used to slice the
            corresponding vectors array to extract only unique vectors. Returns an
            empty list if all IDs are duplicates or already indexed.

        Notes
        -----
        This method is used by update_index() to filter vectors before adding them
        to the secondary index. It performs three levels of deduplication: within
        batch, against secondary index, and against primary index. Time complexity:
        O(n) where n is the number of IDs, plus O(k) for primary_contains checks
        where k is the number of unique IDs in the batch. Space complexity: O(n) for
        the seen_in_batch set. The method is deterministic and preserves the order
        of first occurrence for unique IDs.
        """
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
        """Emit structured log event for secondary index vector additions.

        This helper method logs information about vectors added to the secondary
        index, including the number of vectors added in the current operation,
        the total number of vectors in the secondary index after the addition,
        and the number of duplicate IDs that were skipped. Used for observability
        and debugging of incremental update operations.

        Parameters
        ----------
        added : int
            Number of vectors successfully added to the secondary index in the
            current operation. Must be non-negative. Represents the count of
            unique vectors that passed duplicate filtering.
        total_secondary_vectors : int
            Total number of vectors in the secondary index after the current
            addition. Must be >= added. Used to track the size of the secondary
            index over time.
        skipped_duplicates : int
            Number of duplicate IDs that were filtered out and not added to the
            secondary index. Must be non-negative. Includes IDs that were already
            in the primary index, already in the secondary index, or duplicated
            within the current batch.

        Notes
        -----
        This method emits structured logs with component="faiss_manager" for
        consistent log filtering and analysis. The log event is emitted at INFO
        level and includes all three metrics for comprehensive observability.
        Time complexity: O(1). The method performs no I/O operations beyond logging.
        """
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

    def load_cpu_index(
        self,
        *,
        export_idmap: Path | None = None,
        profile_path: Path | None = None,
    ) -> None:
        """Load CPU index from disk.

        Reads a previously saved FAISS index from index_path and loads it into
        memory. This allows reusing an index without rebuilding it, which is much
        faster for large indexes. Optionally exports the ID map and writes tuning
        profile files for debugging and performance analysis.

        After loading, you can call clone_to_gpu() to create a GPU version for
        faster search, or use search() directly with the CPU index.

        Parameters
        ----------
        export_idmap : Path | None
            Optional path to export the FAISS ID map as a Parquet file. If provided,
            the ID map is written to this location. Defaults to None.
        profile_path : Path | None
            Optional path to write the autotune profile JSON. If provided, the
            current tuning profile is persisted. If None, uses autotune_profile_path.
            Defaults to None.

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
        profile = self._load_tuned_profile()
        if profile:
            try:
                self._apply_profile_payload(profile, persist=False)
            except VectorIndexIncompatibleError as exc:
                LOGGER.warning(
                    "Unable to apply tuning profile during load; continuing with defaults",
                    extra=_log_extra(error=str(exc)),
                )
        self._write_meta_snapshot(
            vector_count=cpu_index.ntotal,
            parameter_space=self._format_parameter_string(self._runtime_overrides),
        )
        if export_idmap is not None:
            try:
                self.export_idmap(export_idmap)
            except RuntimeError as exc:
                LOGGER.warning(
                    "faiss.idmap.export_failed",
                    extra=_log_extra(path=str(export_idmap), error=str(exc)),
                )
        profile_target = profile_path or self.autotune_profile_path
        if profile_target is not None:
            try:
                self._write_profile(profile_target)
            except OSError as exc:
                LOGGER.warning(
                    "faiss.profile.persist_failed",
                    extra=_log_extra(path=str(profile_target), error=str(exc)),
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
        catalog: object | None = None,
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
        catalog : object | None, optional
            Optional catalog object (typically DuckDBCatalog) for candidate hydration
            and exact reranking. When provided and ``refine_k_factor`` > 1, candidate
            embeddings are hydrated from the catalog and reranked exactly before
            returning results. The catalog must expose get_embeddings_by_ids() or
            similar methods for embedding retrieval. When None, reranking is skipped.

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
        metric_labels = self._metric_labels(plan)
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

        span_attrs = {
            Attrs.COMPONENT: "retrieval",
            Attrs.STAGE: "faiss.search",
            Attrs.FAISS_TOP_K: plan.k,
            Attrs.FAISS_NPROBE: plan.params.nprobe,
            Attrs.FAISS_GPU: plan.params.use_gpu,
        }
        with ledger_step(
            stage="pool_search",
            op="faiss.search",
            component="retrieval.faiss",
            attrs={
                Attrs.FAISS_TOP_K: plan.k,
                Attrs.FAISS_NPROBE: plan.params.nprobe,
                Attrs.FAISS_GPU: plan.params.use_gpu,
            },
        ):
            with span_context(
                "search.faiss",
                stage="search.faiss",
                attrs=span_attrs,
                emit_checkpoint=True,
            ):
                start = perf_counter()
                ann_timer_start = start
                try:
                    distances, identifiers = self._execute_dual_search(
                        query=plan.queries,
                        search_k=plan.search_k,
                        params=plan.params,
                    )
                    if plan.search_k > 0:
                        FAISS_POSTFILTER_DENSITY.labels(**metric_labels).set(
                            plan.k / float(plan.search_k)
                        )
                    duck_catalog = catalog if isinstance(catalog, DuckDBCatalog) else None
                    refined = self._maybe_refine_results(
                        catalog=duck_catalog,
                        plan=plan,
                        identifiers=identifiers,
                        metric_labels=metric_labels,
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
                    emit_step(
                        StepEvent(
                            kind="faiss.search",
                            status="failed",
                            detail=type(exc).__name__,
                            payload={
                                "k": plan.k,
                                "nprobe": plan.params.nprobe,
                                "use_gpu": plan.params.use_gpu,
                            },
                        )
                    )
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
                    FAISS_ANN_LATENCY_SECONDS.labels(**metric_labels).observe(duration)

        elapsed_total = (perf_counter() - start) * 1000.0
        FAISS_SEARCH_LATENCY_SECONDS.observe(elapsed_total / 1000.0)
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
        emit_step(
            StepEvent(
                kind="faiss.search",
                status="completed",
                payload={
                    "k": plan.k,
                    "nprobe": plan.params.nprobe,
                    "use_gpu": plan.params.use_gpu,
                    "duration_ms": int(elapsed_total),
                },
            )
        )
        self._last_latency_ms = elapsed_total
        FAISS_SEARCH_LAST_MS.set(elapsed_total)
        return result

    def search_with_refine(
        self,
        query: NDArrayF32,
        *,
        k: int,
        catalog: DuckDBCatalog,
        config: RefineSearchConfig | None = None,
    ) -> list[SearchHit]:
        """Return structured hits with ANN search + exact rerank metadata.

        Parameters
        ----------
        query : NDArrayF32
            Query vector for ANN search. Must match the index dimension.
        k : int
            Number of results to return after reranking.
        catalog : DuckDBCatalog
            DuckDB catalog for fetching chunk metadata and embeddings for
            reranking. Used to hydrate candidate IDs into full chunk records.
        config : RefineSearchConfig | None, optional
            Optional configuration bundle controlling nprobe, runtime overrides,
            and telemetry source. When None, uses default settings (nprobe from
            manager configuration, telemetry source ``faiss``).

        Returns
        -------
        list[SearchHit]
            List of SearchHit objects containing chunk metadata, scores, and
            rerank information. Results are sorted by rerank score (descending)
            when reranking is enabled, or by ANN distance (ascending) otherwise.
        """
        config = config or RefineSearchConfig()
        runtime = config.runtime or SearchRuntimeOverrides()
        _, _, resolved_k_factor, _ = self._resolve_search_knobs(
            override_nprobe=config.nprobe,
            override_ef=runtime.ef_search,
            override_k_factor=runtime.k_factor,
            override_quantizer=runtime.quantizer_ef_search,
        )
        distances, identifiers = self.search(
            query,
            k=k,
            nprobe=config.nprobe,
            runtime=runtime,
            catalog=catalog,
        )
        if distances.size == 0 or identifiers.size == 0:
            return []
        top_scores = distances[0]
        top_ids = identifiers[0]
        hits: list[SearchHit] = []
        for rank, (chunk_id, score) in enumerate(zip(top_ids, top_scores, strict=True)):
            if chunk_id < 0:
                continue
            hits.append(
                SearchHit(
                    doc_id=str(int(chunk_id)),
                    rank=rank,
                    score=float(score),
                    source=config.source,
                    faiss_row=None,
                    explain={
                        "family": self.faiss_family or "auto",
                        "k_factor": resolved_k_factor,
                    },
                )
            )
        return hits

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

    def apply_tuning_profile(self, profile: Mapping[str, Any]) -> dict[str, object]:
        """Apply a persisted tuning profile (typically from ``tuning.json``).

        Parameters
        ----------
        profile : Mapping[str, Any]
            Tuning profile dictionary containing runtime parameter overrides.
            Expected keys include "param_str", "nprobe", "efSearch", "k_factor",
            etc. The profile is typically loaded from a tuning.json file created
            by the tuning process.

        Returns
        -------
        dict[str, object]
            Current runtime tuning parameters after applying the profile. Returns
            the same dictionary as get_runtime_tuning(), containing all active
            runtime parameter overrides.

        Raises
        ------
        VectorIndexIncompatibleError
            Raised when the profile is empty or invalid. Profiles must contain
            at least one valid parameter override.
        """
        if not profile:
            msg = "Tuning profile payload is empty."
            raise VectorIndexIncompatibleError(msg)

        snapshot = self._apply_profile_payload(profile, persist=True)
        return snapshot

    def _apply_profile_payload(
        self,
        profile: Mapping[str, Any],
        *,
        persist: bool,
    ) -> dict[str, object]:
        overrides = _parse_tuning_overrides(profile)
        try:
            if overrides.param_str:
                snapshot = self.set_search_parameters(overrides.param_str)
            else:
                snapshot = self.apply_runtime_tuning(
                    nprobe=overrides.nprobe,
                    ef_search=overrides.ef_search,
                    quantizer_ef_search=overrides.quantizer_ef_search,
                    k_factor=overrides.k_factor,
                )
        except (ValueError, TypeError) as exc:
            error_msg = "Unable to apply tuning profile."
            raise VectorIndexIncompatibleError(
                error_msg,
                context={"param_str": overrides.param_str or "runtime_overrides"},
                cause=exc,
            ) from exc

        if overrides.k_factor is not None:
            with self._tuning_lock:
                self.refine_k_factor = overrides.k_factor
        if persist:
            _persist_tuning_profile(self, profile)
        else:
            self._tuned_parameters = dict(profile)
        return snapshot

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
        search_attrs = {
            Attrs.REQUEST_STAGE: "dense",
            Attrs.FAISS_TOP_K: search_k,
            Attrs.FAISS_NPROBE: params.nprobe or -1,
            Attrs.FAISS_GPU: params.use_gpu,
            Attrs.FAISS_INDEX_TYPE: str(self.faiss_family or "auto"),
        }
        search_span = span_context(
            "faiss.search",
            stage="search.faiss",
            attrs=search_attrs,
            emit_checkpoint=True,
        )
        with search_span:
            self._apply_runtime_parameters(
                nprobe=params.nprobe,
                ef_search=params.ef_search,
                quantizer_ef_search=params.quantizer_ef_search,
            )
            with span_context(
                "faiss.search.primary",
                stage="search.faiss.primary",
                attrs={Attrs.FAISS_NPROBE: params.nprobe or -1},
            ):
                primary_dists, primary_ids = self._search_primary(query, search_k, params.nprobe)
            if self.secondary_index is None:
                record_span_event(
                    "faiss.search.primary_only",
                    candidates=int(primary_ids.shape[1]),
                )
                return primary_dists, primary_ids
            with span_context(
                "faiss.search.secondary",
                stage="search.faiss.secondary",
                attrs={Attrs.FAISS_INDEX_TYPE: "secondary"},
            ):
                secondary_dists, secondary_ids = self._search_secondary(query, search_k)
            with span_context(
                "faiss.search.merge",
                stage="search.faiss.merge",
                attrs={
                    "primary_candidates": int(primary_ids.shape[1]),
                    "secondary_candidates": int(secondary_ids.shape[1]),
                },
            ):
                merged_dists, merged_ids = self._merge_results(
                    primary_dists,
                    primary_ids,
                    secondary_dists,
                    secondary_ids,
                    search_k,
                )
            record_span_event(
                "faiss.search.merge_result",
                primary=primary_ids.shape[1],
                secondary=secondary_ids.shape[1],
                merged=merged_ids.shape[1],
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
        metric_labels: Mapping[str, str] | None = None,
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
        metric_labels : Mapping[str, str] | None, optional
            Prometheus metric labels applied when recording refinement latency.
            When None, falls back to the unlabeled histogram variant.

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
            with ledger_step(
                stage="rerank",
                op="faiss.refine",
                component="retrieval.faiss",
                attrs={
                    Attrs.RETRIEVAL_TOP_K: plan.k,
                    Attrs.FAISS_TOP_K: plan.search_k,
                },
            ):
                reranker = FlatReranker(catalog)
                rerank_scores, rerank_ids = reranker.rerank(
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
        duration = max(perf_counter() - refine_start, 0.0)
        if metric_labels is not None:
            FAISS_REFINE_LATENCY_SECONDS.labels(**metric_labels).observe(duration)
        else:  # pragma: no cover - legacy path
            FAISS_REFINE_LATENCY_SECONDS.observe(duration)
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
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=3584)
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
        VectorIndexStateError
            If the index has not been built or loaded yet.
        """
        if self.cpu_index is None:
            msg = "FAISS index not built or loaded"
            raise VectorIndexStateError(msg, context={"index_path": str(self.index_path)})
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
                apply_parameters(index, param_str)
            except ValueError as exc:
                LOGGER.warning(
                    "Failed to apply FAISS parameters",
                    extra=_log_extra(param_str=param_str, error=str(exc)),
                )
        distances, ids = index.search(xq, k)
        if refine_k_factor and refine_k_factor > 1.0:
            distances, ids = self._refine_with_flat(xq, ids, k)
        return distances, ids

    def _save_tuning_profile(
        self,
        profile: Mapping[str, Any],
        *,
        path: Path | None = None,
    ) -> Path:
        """Persist ``profile`` to ``tuning.json`` and return its path.

        This method saves an autotune profile (containing parameter strings, recall
        metrics, latency measurements, and other tuning metadata) to a JSON file.
        The profile is serialized with indentation for readability and stored at
        the configured autotune profile path or a custom path if specified. The
        parent directory is created if it doesn't exist.

        Parameters
        ----------
        profile : Mapping[str, Any]
            Autotune profile dictionary containing tuning results. Typically includes
            keys like "param_str" (parameter string), "recall_at_k" (recall metric),
            "latency_ms" (search latency), and "refine_k_factor" (refinement factor).
            The dictionary is serialized to JSON format.
        path : Path | None, optional
            Custom file system path to save the profile to. If None, uses the
            configured autotune_profile_path. The parent directory is created
            automatically if it doesn't exist.

        Returns
        -------
        Path
            File system path where the tuning profile was saved. This is either
            the provided path or the default autotune_profile_path. The path
            points to a JSON file containing the serialized profile data.

        Notes
        -----
        This method performs file I/O to persist autotune results for later use.
        The profile JSON file can be loaded to restore optimal tuning parameters
        without re-running autotune. Time complexity: O(n) where n is the size of
        the profile dictionary. The method creates parent directories if needed and
        overwrites existing files. Thread-safe if file system operations are atomic.
        """
        target = path or self.autotune_profile_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        return target

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
        tuner = AutoTuner(self)
        profile = tuner.run_sweep(queries, truths, k=k, sweep=sweep)
        timestamp = datetime.now(UTC).isoformat()
        profile["profile_at"] = timestamp
        profile.setdefault("updated_at", timestamp)
        try:
            self._save_tuning_profile(profile)
        except OSError as exc:  # pragma: no cover - best-effort logging
            LOGGER.warning(
                "Failed to persist FAISS autotune profile",
                extra=_log_extra(path=str(self.autotune_profile_path), error=str(exc)),
            )
        self._tuned_parameters = dict(profile)
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
        """Calculate the number of IVF centroids (nlist) based on corpus size.

        This method computes the optimal number of IVF centroids (nlist) for
        building IVF-family indexes. When faiss_family is "auto", it uses a
        square-root heuristic (sqrt(n_vectors)) which balances training time
        and search recall. When a specific family is configured, it uses the
        configured nlist value. The result is always bounded by the minimum
        parameter to ensure reasonable index structure.

        Parameters
        ----------
        n_vectors : int
            Number of vectors in the corpus. Used to compute nlist when in auto
            mode. Must be positive. Larger corpora result in larger nlist values
            (up to the configured maximum).
        minimum : int
            Minimum nlist value to return. Ensures the index has at least this
            many centroids even for small corpora. Typically 100 for medium
            corpora, 1024 for large corpora.

        Returns
        -------
        int
            Computed nlist value for IVF index construction. When faiss_family
            is "auto", returns max(sqrt(n_vectors), minimum). When a specific
            family is configured, returns max(configured_nlist, minimum). The
            value is always >= minimum.

        Notes
        -----
        The square-root heuristic (sqrt(n_vectors)) is a common practice in
        FAISS indexing that balances training time (O(nlist * log(nlist))) and
        search recall. More centroids improve recall but increase training time
        and memory usage. The method is deterministic and has O(1) time complexity.
        """
        if self.faiss_family != "auto":
            return max(self.nlist, minimum)
        return max(int(np.sqrt(n_vectors)), minimum)

    def _factory_string_for(self, family: str, _n_vectors: int) -> str:
        """Generate a FAISS index factory string for the specified family.

        This method converts a family name (e.g., "ivf_pq", "hnsw") into a
        FAISS index factory string that can be passed to faiss.index_factory().
        The factory string encodes the index structure, including quantization
        parameters (PQ codes, OPQ preprocessing), IVF centroids (nlist), and
        HNSW graph parameters (m). The string format follows FAISS conventions
        for index construction.

        Parameters
        ----------
        family : str
            Index family name (case-insensitive). Valid values: "flat", "ivf_flat",
            "ivf_pq", "ivf_pq_refine", "hnsw". Determines the index structure
            and quantization strategy. Unknown families default to "Flat".
        _n_vectors : int
            Number of vectors (unused, kept for API compatibility). The factory
            string does not depend on corpus size, only on the configured family
            and runtime options.

        Returns
        -------
        str
            FAISS index factory string suitable for faiss.index_factory(). Examples:
            - "Flat" for exact search
            - "IVF8192,Flat" for IVFFlat with 8192 centroids
            - "OPQ64,IVF8192,PQ64x8" for IVF-PQ with OPQ preprocessing
            - "HNSW32" for HNSW with m=32
            The string format matches FAISS ParameterSpace conventions.

        Notes
        -----
        This method is used by build_index() when a specific family is requested
        (non-auto mode). The factory string incorporates runtime options like
        pq_m, pq_nbits, opq_m, hnsw_m, and nlist. Time complexity: O(1). The
        method is deterministic and case-insensitive for family names.
        """
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
        """Record the selected index factory and persist metadata.

        This method logs the index factory choice, updates Prometheus metrics,
        and persists index metadata to disk. It extracts the index type name
        (either from the provided label or by inspecting the index object),
        records it in metrics, and writes a metadata snapshot including factory
        name, vector count, and parameter space configuration.

        Parameters
        ----------
        index : _faiss.Index
            FAISS index object that was built or loaded. Used to extract the
            index type name if label is not provided. The index must be
            initialized (ntotal >= 0).
        label : str | None, optional
            Optional factory label to use instead of inferring from the index
            type. When provided, this label is used for logging and metrics.
            When None, the method attempts to extract the type name from the
            index object via downcast_index().
        parameter_space : str | None, optional
            Optional FAISS ParameterSpace parameter string (e.g., "nprobe=64").
            When provided, included in the metadata snapshot. Used to track
            runtime tuning parameters applied to the index.
        vector_count : int | None, optional
            Optional vector count to record in metadata. When None, uses
            index.ntotal to determine the count. When provided, overrides the
            index's ntotal value. Used to record the number of vectors used
            during index construction.

        Notes
        -----
        This method is called after index construction or loading to record the
        index configuration for observability and persistence. It updates
        Prometheus metrics (set_factory_id) and writes metadata to the meta JSON
        file. Time complexity: O(1) for logging and metrics, O(n) for metadata
        serialization where n is the metadata size. The method performs file I/O
        to persist metadata and is not thread-safe if called concurrently.
        """
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
        """Apply runtime search knobs to the active FAISS index.

        This method applies runtime tuning parameters (nprobe, efSearch,
        quantizer_efSearch) to the active FAISS index using the ParameterSpace
        API. These parameters control search behavior: nprobe controls IVF cell
        traversal, efSearch controls HNSW graph exploration, and quantizer_efSearch
        controls quantizer search depth. The method falls back to direct attribute
        assignment if ParameterSpace API is unavailable.

        Parameters
        ----------
        nprobe : int | None
            Number of IVF cells to probe during search. Higher values improve
            recall but slow down search. Only applies to IVF-family indexes.
            When None, the parameter is not applied.
        ef_search : int | None
            HNSW exploration factor controlling graph traversal depth. Higher
            values improve recall but slow down search. Only applies to HNSW
            indexes. When None, the parameter is not applied.
        quantizer_ef_search : int | None, optional
            Exploration factor for IVF quantizer search (default: None). Controls
            quantizer traversal depth for hierarchical IVF indexes. When None,
            the parameter is not applied.

        Notes
        -----
        This method modifies the index object in-place, affecting all subsequent
        search operations until parameters are changed again. The method attempts
        to use FAISS ParameterSpace API first, then falls back to direct attribute
        assignment (e.g., index.nprobe) if ParameterSpace is unavailable. Time
        complexity: O(1) for parameter application. The method is not thread-safe
        if the index is being used concurrently. Parameters persist for the lifetime
        of the index object or until explicitly changed.
        """
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

    def _metric_labels(self, plan: _SearchPlan) -> dict[str, str]:
        """Generate Prometheus metric labels from a search plan.

        This method constructs a dictionary of metric labels for Prometheus
        histograms and counters based on the search plan parameters. The labels
        include index family, nprobe setting, ef_search setting, and refine_k_factor
        (computed as search_k / k). These labels enable fine-grained metric
        aggregation and analysis of search performance across different index
        configurations and parameter settings.

        Parameters
        ----------
        plan : _SearchPlan
            Search plan containing queries, effective k, search_k (with k_factor
            expansion), and execution parameters (nprobe, ef_search, etc.). Used
            to extract parameter values for metric labeling.

        Returns
        -------
        dict[str, str]
            Dictionary of Prometheus metric labels with keys:
            - "index_family": Index family name ("auto", "ivf_pq", "hnsw", etc.)
            - "nprobe": nprobe value as string, or "default" if None
            - "ef_search": ef_search value as string, or empty string if None
            - "refine_k_factor": Ratio of search_k to k, formatted as "X.XX"
            All values are strings as required by Prometheus label constraints.

        Notes
        -----
        This method is used by search() to label Prometheus metrics (e.g.,
        FAISS_ANN_LATENCY_SECONDS, FAISS_REFINE_LATENCY_SECONDS) for dimensional
        analysis. The refine_k_factor is computed as search_k / k to represent
        candidate expansion ratio. Time complexity: O(1). The method is deterministic
        and produces consistent labels for the same search plan.
        """
        ratio = plan.search_k / plan.k if plan.k > 0 else 0.0
        return {
            "index_family": str(self.faiss_family or "auto"),
            "nprobe": str(plan.params.nprobe or "default"),
            "ef_search": str(plan.params.ef_search or ""),
            "refine_k_factor": f"{ratio:.2f}",
        }

    def _maybe_apply_runtime_parameters(self, overrides: Mapping[str, float | int]) -> None:
        """Best-effort application of overrides to the live index if available.

        This method attempts to apply runtime parameter overrides to the active
        FAISS index, but gracefully handles failures without raising exceptions.
        It extracts nprobe, efSearch, and quantizer_efSearch from the overrides
        dictionary and applies them via _apply_runtime_parameters(). If the index
        is unavailable or parameter application fails, the method logs a debug
        message and continues without error.

        Parameters
        ----------
        overrides : Mapping[str, float | int]
            Dictionary of runtime parameter overrides with keys "nprobe", "efSearch",
            or "quantizer_efSearch". Values are converted to integers before
            application. Empty dictionaries result in no-op. Unrecognized keys are
            ignored.

        Notes
        -----
        This method is used by apply_runtime_tuning() and reset_runtime_tuning()
        to update the live index when overrides are changed. The method is
        best-effort: it does not raise exceptions if the index is unavailable
        or parameter application fails, allowing the override dictionary to be
        updated even when the index is not ready. Time complexity: O(1) plus
        the cost of _apply_runtime_parameters(). The method performs no I/O
        operations and is safe to call even when the index is not initialized.
        """
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
                apply_parameters(self._active_index(), faiss_spec)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
        with self._tuning_lock:
            self._runtime_overrides.update(sanitized)
        self._write_meta_snapshot(
            parameter_space=self._format_parameter_string(self._runtime_overrides)
        )
        return self.get_runtime_tuning()

    def _prepare_parameter_string(self, param_str: str) -> tuple[str | None, dict[str, float]]:
        """Parse and validate a FAISS parameter string into FAISS spec and overrides.

        This method parses a comma-separated parameter string (e.g., "nprobe=64,efSearch=128")
        into two components: (1) a FAISS ParameterSpace string for direct index
        application, and (2) a sanitized override dictionary for persistence. The
        method validates parameter names (must be supported), values (must be numeric),
        and constraints (positive integers, k_factor >= 1.0). The k_factor parameter
        is excluded from the FAISS spec (it's manager-specific) but included in overrides.

        Parameters
        ----------
        param_str : str
            Comma-separated parameter string in format "key1=value1,key2=value2".
            Supported keys: "nprobe", "efSearch", "quantizer_efSearch", "k_factor".
            Values must be numeric. Whitespace around keys/values is stripped.
            Must be non-empty and contain at least one valid parameter.

        Returns
        -------
        tuple[str | None, dict[str, float]]
            Tuple containing:
            - FAISS ParameterSpace string (e.g., "nprobe=64,efSearch=128") for
              direct index application, or None if no FAISS parameters are present
              (only k_factor was specified)
            - Sanitized override dictionary with validated parameters, ready for
              storage in _runtime_overrides. Always non-empty (raises ValueError
              if empty after parsing).

        Raises
        ------
        ValueError
            Raised in the following cases:
            - param_str is empty or whitespace-only: parameter string must be non-empty
            - Invalid parameter fragment: malformed key=value pair (missing =, empty key/value)
            - Non-numeric parameter value: value cannot be converted to float
            - Unsupported parameter name: key is not in the supported set
            - Parameter validation fails: value violates constraints (see _sanitize_runtime_overrides)
            - No valid parameters: all parameters were invalid or only k_factor was provided
              (k_factor alone is insufficient)

        Notes
        -----
        This method is used by set_search_parameters() to parse user-provided parameter
        strings. It separates FAISS-specific parameters (for direct index application)
        from manager-specific parameters (k_factor, for override storage). The method
        performs comprehensive validation and provides clear error messages. Time
        complexity: O(n) where n is the length of param_str. The method is deterministic
        and raises exceptions for invalid inputs.
        """
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
        """Format runtime override dictionary into a parameter string.

        This method converts a dictionary of runtime parameter overrides into a
        comma-separated parameter string suitable for display or persistence.
        Parameters are formatted in a canonical order (nprobe, efSearch,
        quantizer_efSearch, k_factor) with integer parameters formatted as integers
        and k_factor formatted as a float. The resulting string can be parsed back
        by _prepare_parameter_string().

        Parameters
        ----------
        overrides : Mapping[str, float]
            Dictionary of runtime parameter overrides with keys "nprobe", "efSearch",
            "quantizer_efSearch", and/or "k_factor". Values are expected to be
            numeric (integers or floats). Only recognized keys are included in the
            output; unknown keys are ignored.

        Returns
        -------
        str | None
            Comma-separated parameter string (e.g., "nprobe=64,efSearch=128,k_factor=2.0")
            with parameters in canonical order. Integer parameters are formatted without
            decimal points; k_factor retains decimal precision. Returns None if the
            dictionary is empty or contains no recognized parameters.

        Notes
        -----
        This method is used by _write_meta_snapshot() and get_runtime_tuning() to
        serialize override dictionaries for persistence and display. The method
        ensures consistent formatting and ordering for readability. Time complexity:
        O(1) since the number of parameters is fixed. The method is deterministic
        and produces consistent output for the same input dictionary.
        """
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
        """Load and update index metadata snapshot from disk.

        This method loads the existing metadata JSON file (if present) and merges
        it with current manager configuration to create a comprehensive metadata
        snapshot. The snapshot includes index path, vector dimension, FAISS family,
        default parameters, and any previously persisted metadata (factory name,
        vector count, parameter space, etc.). Used as a base for _write_meta_snapshot()
        to preserve existing metadata while updating specific fields.

        Returns
        -------
        dict[str, object]
            Metadata snapshot dictionary containing:
            - "index_path": String path to the index file
            - "vec_dim": Vector dimension (int)
            - "faiss_family": Index family name (str)
            - "default_parameters": Dictionary with default nprobe, efSearch,
              quantizer_efSearch, and k_factor values
            - Any additional fields from the existing metadata file (factory,
              vector_count, parameter_space, runtime_overrides, etc.)
            Returns a fresh dictionary with current configuration if the metadata
            file doesn't exist or is invalid JSON.

        Notes
        -----
        This method performs file I/O to read the metadata JSON file. If the file
        doesn't exist or contains invalid JSON, it returns a dictionary with current
        configuration only. The method merges existing metadata with current settings,
        allowing incremental updates without losing historical data. Time complexity:
        O(1) for file existence check, O(n) for JSON parsing where n is file size.
        The method handles JSON decode errors gracefully, returning an empty base
        dictionary.
        """
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
        """Write index metadata snapshot to disk.

        This method creates or updates the index metadata JSON file with current
        manager configuration, runtime overrides, compile options, and optional
        update fields (factory name, vector count, parameter space). The metadata
        file serves as a persistent record of index configuration for observability,
        debugging, and index lifecycle management. The file is written with JSON
        indentation for readability.

        Parameters
        ----------
        factory : str | None, optional
            Optional factory name (index type) to record in metadata. When provided,
            updates the "factory" field. When None, preserves existing factory value
            or leaves it unset. Used to track the index structure (e.g., "IVF8192,Flat").
        vector_count : int | None, optional
            Optional vector count to record in metadata. When provided, updates the
            "vector_count" field. When None, preserves existing count or leaves it
            unset. Used to track the number of vectors in the index.
        parameter_space : str | None, optional
            Optional FAISS ParameterSpace parameter string to record in metadata.
            When provided, updates the "parameter_space" field. When None, preserves
            existing parameter space or leaves it unset. Used to track runtime tuning
            parameters (e.g., "nprobe=64,efSearch=128").

        Notes
        -----
        This method performs file I/O to write the metadata JSON file. The parent
        directory is created if it doesn't exist. The metadata includes a timestamp
        (updated_at) in ISO format for tracking when the snapshot was last updated.
        Time complexity: O(n) where n is the metadata size for JSON serialization,
        plus file I/O overhead. The method overwrites the existing metadata file
        and is not thread-safe if called concurrently.
        """
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

    @staticmethod
    def get_compile_options() -> str:
        """Return FAISS compile options string when available.

        Returns
        -------
        str
            Compile-time configuration string for FAISS, including enabled
            features and build flags. Returns an empty string if compile options
            are not available.
        """
        return _get_compile_options()

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
        """Load autotune profile from disk with caching.

        This method loads the persisted autotune profile (tuning results) from the
        JSON file, caches it in _tuned_parameters for subsequent access, and returns
        the profile dictionary. The profile contains optimal parameter settings
        discovered during autotune sweeps, including param_str, recall_at_k, latency_ms,
        and extracted parameter values (nprobe, efSearch, etc.). The method handles
        file I/O errors and JSON parsing errors gracefully, returning an empty
        dictionary when the profile cannot be loaded.

        Returns
        -------
        dict[str, float | str]
            Autotune profile dictionary containing tuning results. Typical keys include:
            - "param_str": Best parameter string (str)
            - "recall_at_k": Best recall metric (float)
            - "latency_ms": Search latency for best config (float)
            - "nprobe", "efSearch", etc.: Extracted parameter values (float/int)
            Returns the cached profile if already loaded, or an empty dictionary if
            the profile file doesn't exist, cannot be read, or contains invalid JSON.

        Notes
        -----
        This method implements caching: the profile is loaded once and stored in
        _tuned_parameters for subsequent calls. The method checks both the primary
        autotune profile path and legacy path for backward compatibility. Time
        complexity: O(1) if cached, O(n) for file I/O and JSON parsing where n is
        file size. The method performs file I/O and handles errors gracefully without
        raising exceptions. Thread-safe if called under lock protection (as used in
        _resolve_search_knobs).
        """
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
        """Determine the autotune profile file path for reading.

        This method checks for the existence of autotune profile files in order of
        preference: (1) primary autotune profile path (autotune_profile_path),
        (2) legacy autotune profile path (_legacy_autotune_profile_path). Returns
        the first path that exists, or None if neither file exists. This enables
        backward compatibility with older profile file locations while preferring
        the new location.

        Returns
        -------
        Path | None
            Path to the autotune profile JSON file if it exists, or None if neither
            the primary nor legacy profile files are present. The returned path can
            be used to read the profile data. Returns the primary path if both exist.

        Notes
        -----
        This method performs file system checks to determine which profile file to
        use. The legacy path uses a different naming convention (.tune.json suffix
        vs tuning.json filename) for backward compatibility. Time complexity: O(1)
        for file existence checks. The method performs no I/O operations beyond
        existence checks and is deterministic.
        """
        if self.autotune_profile_path.exists():
            return self.autotune_profile_path
        if self._legacy_autotune_profile_path.exists():
            return self._legacy_autotune_profile_path
        return None

    def _timed_search_with_params(
        self, queries: NDArrayF32, k: int, param_str: str
    ) -> tuple[float, tuple[NDArrayF32, NDArrayI64]]:
        """Execute a parameterized search and measure its latency.

        This method performs a FAISS search with the specified parameter string
        and measures the execution time in milliseconds. It wraps _search_with_params()
        with timing instrumentation, recording the elapsed time from start to completion.
        Used by autotune sweeps to evaluate parameter configurations and select optimal
        settings based on recall and latency trade-offs.

        Parameters
        ----------
        queries : NDArrayF32
            Query vector(s) to search, shape (n_queries, vec_dim) or (vec_dim,).
            Automatically normalized for cosine similarity by _search_with_params().
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
            - Search results tuple: (distances, ids) arrays from _search_with_params(),
              both with shape (n_queries, k). Distances are cosine similarity scores;
              IDs are chunk identifiers.

        Notes
        -----
        This method is used by AutoTuner.run_sweep() to evaluate parameter
        configurations during autotune sweeps. The timing measurement uses
        perf_counter() for high-resolution, monotonic timing that is not affected
        by system clock adjustments. Time complexity: O(search_time) where search_time
        depends on index type and parameters, plus O(1) for timing overhead. The
        method modifies the index parameters in-place before search, affecting
        subsequent searches until parameters are changed again.
        """
        start = perf_counter()
        result = self._search_with_params(queries, k, param_str=param_str)
        elapsed = (perf_counter() - start) * 1000.0
        return elapsed, result

    @staticmethod
    def _brute_force_truth_ids(queries: NDArrayF32, truths: NDArrayF32, k: int) -> NDArrayI64:
        """Compute ground-truth nearest neighbor IDs via exact brute-force search.

        This method performs exact nearest neighbor search by computing the full
        similarity matrix (queries @ truths.T) and selecting the top-k most similar
        truth vectors for each query. It uses argpartition for efficient top-k
        selection without full sorting. The result provides ground-truth IDs for
        recall evaluation during autotune sweeps.

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
        This method is used by AutoTuner.run_sweep() to compute ground-truth nearest
        neighbors for recall evaluation. It performs exact search via matrix
        multiplication (O(n_queries * n_truths * vec_dim)) and argpartition
        (O(n_queries * n_truths * log(k))) for top-k selection. The method assumes
        vectors are normalized for cosine similarity (inner product). Time complexity:
        O(n_queries * n_truths * vec_dim) for similarity computation plus O(n_queries
        * n_truths * log(k)) for top-k selection. Space complexity: O(n_queries * n_truths)
        for the similarity matrix.
        """
        sims = queries @ truths.T
        k = min(k, sims.shape[1])
        if k <= 0:
            return np.empty((queries.shape[0], 0), dtype=np.int64)
        idx = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
        return idx.astype(np.int64)

    @staticmethod
    def _estimate_recall(candidates: NDArrayI64, truth: NDArrayI64) -> float:
        """Compute recall@k metric by comparing candidates against ground truth.

        This method computes the average recall@k across all queries by comparing
        candidate IDs returned from FAISS search against ground-truth nearest
        neighbor IDs. Recall is computed as the fraction of ground-truth IDs that
        appear in the candidate set, averaged across all queries. The metric ranges
        from 0.0 (no matches) to 1.0 (all ground-truth IDs found).

        Parameters
        ----------
        candidates : NDArrayI64
            Candidate IDs returned from FAISS search, shape (n_queries, k_candidates).
            Each row contains chunk IDs (or indices) from approximate search results.
            Negative values are treated as invalid and ignored.
        truth : NDArrayI64
            Ground-truth nearest neighbor IDs (or indices), shape (n_queries, k_truth).
            Each row contains the true top-k nearest neighbor IDs from exact search.
            Negative values are treated as invalid and ignored. Must have the same
            number of rows (n_queries) as candidates.

        Returns
        -------
        float
            Average recall@k metric in the range [0.0, 1.0]. Computed as the mean
            of per-query recall values, where each query's recall is the fraction
            of ground-truth IDs found in the candidate set. Returns 0.0 if either
            array is empty or if there are no queries (total == 0).

        Notes
        -----
        This method is used by AutoTuner.run_sweep() to evaluate search quality
        during parameter sweeps. The recall metric measures how well approximate
        search results match exact (brute-force) search results. The method handles
        variable-length ground truth sets (queries with no ground truth are skipped)
        and invalid IDs (negative values). Time complexity: O(n_queries * (k_candidates
        + k_truth)) for set operations and comparisons. Space complexity: O(k_truth)
        per query for truth set construction. The method is deterministic and produces
        consistent results for the same input arrays.
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

    @staticmethod
    def _ensure_2d(array: NDArrayF32) -> NDArrayF32:
        """Ensure an array is 2-dimensional for consistent FAISS search interface.

        This helper method normalizes array shapes for FAISS search operations, which
        expect 2D arrays with shape (n_queries, vec_dim). Single query vectors
        (1D arrays with shape (vec_dim,)) are reshaped to (1, vec_dim) to maintain
        consistent array dimensions. Multi-query arrays are returned unchanged.

        Parameters
        ----------
        array : NDArrayF32
            Input array that may be 1D or 2D. Shape (vec_dim,) for single query or
            (n_queries, vec_dim) for multiple queries. Dtype is converted to float32
            if not already. The array is copied if reshaping is needed.

        Returns
        -------
        NDArrayF32
            Normalized 2D array with shape (n_queries, vec_dim) where n_queries >= 1.
            Single query vectors are reshaped from (vec_dim,) to (1, vec_dim).
            Multi-query arrays are returned unchanged (after dtype conversion).
            Dtype is guaranteed to be float32.

        Notes
        -----
        This method is used throughout the FAISS manager to normalize query inputs
        before search operations. It ensures consistent array shapes for FAISS API
        calls and simplifies handling of both single and batch queries. Time
        complexity: O(1) for shape check, O(n) for dtype conversion where n is
        array size. The method may create a copy if dtype conversion or reshaping
        is needed. The method is deterministic and preserves array values.
        """
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


class AutoTuner:
    """Evaluate FAISS ParameterSpace candidates for a given manager."""

    _DEFAULT_SWEEP: tuple[str, ...] = (
        "nprobe=16",
        "nprobe=32",
        "nprobe=64",
        "nprobe=96",
        "nprobe=128",
    )

    def __init__(self, manager: FAISSManager) -> None:
        self._manager = manager

    def run_sweep(
        self,
        queries: NDArrayF32,
        truths: NDArrayF32,
        *,
        k: int = 10,
        sweep: Sequence[str] | None = None,
        refine_k_factor: float | None = None,
    ) -> dict[str, Any]:
        """Return the selected operating-point profile.

        This method performs a parameter sweep over a sequence of FAISS parameter
        strings, evaluating each configuration's recall and latency. The method
        normalizes query and truth vectors, computes ground-truth nearest neighbors,
        and tests each parameter configuration to find the optimal operating point
        balancing recall and latency. The selected profile includes the best
        parameter string, recall metrics, latency measurements, and refinement
        factor.

        Parameters
        ----------
        queries : NDArrayF32
            Query vectors with shape `(N, dim)` and dtype float32. Used to evaluate
            search performance across parameter configurations. Vectors are normalized
            to unit length (L2 normalization) before evaluation.
        truths : NDArrayF32
            Ground-truth vectors with shape `(M, dim)` and dtype float32. Used to
            compute recall metrics by comparing search results against exact nearest
            neighbors. Vectors are normalized to unit length (L2 normalization)
            before evaluation.
        k : int, optional
            Number of nearest neighbors to retrieve per query (defaults to 10).
            Used to compute recall@k metrics and determine ground-truth IDs.
            Must be positive and not exceed the number of truth vectors.
        sweep : Sequence[str] | None, optional
            Sequence of FAISS parameter strings to evaluate (e.g., ["nprobe=16",
            "nprobe=32", "efSearch=64"]). If None, uses the default parameter sweep
            defined by the class. Each parameter string is applied to the index
            and evaluated for recall and latency.
        refine_k_factor : float | None, optional
            Refinement factor to include in the profile. If None, uses the manager's
            default refine_k_factor. Values > 1.0 enable candidate expansion and
            exact reranking for improved recall.

        Returns
        -------
        dict[str, Any]
            Selected operating-point profile dictionary containing:
            - param_str: Best parameter string selected from the sweep
            - recall_at_k: Recall@k metric for the selected configuration (float)
            - latency_ms: Average search latency in milliseconds (float)
            - refine_k_factor: Refinement factor for candidate expansion (float)
            The profile represents the optimal balance between recall and latency
            based on the sweep evaluation criteria.
        """
        xq = self._manager._ensure_2d(queries).astype(
            np.float32
        )  # lint-ignore[SLF001]: share private helper inside module
        xt = self._manager._ensure_2d(truths).astype(
            np.float32
        )  # lint-ignore[SLF001]: share private helper inside module
        faiss.normalize_L2(xq)
        faiss.normalize_L2(xt)
        eval_sweep = tuple(sweep) if sweep else self._DEFAULT_SWEEP
        truth_ids = self._manager._brute_force_truth_ids(
            xq, xt, min(k, xt.shape[0])
        )  # lint-ignore[SLF001]: reuse internal helper for evaluation
        candidates: list[dict[str, float | str]] = []
        for spec in eval_sweep:
            latency_ms, (_, ids) = self._manager._timed_search_with_params(
                xq, k, spec
            )  # lint-ignore[SLF001]: reuse internal helper for evaluation
            recall = self._manager._estimate_recall(
                ids, truth_ids
            )  # lint-ignore[SLF001]: reuse internal helper for evaluation
            candidates.append(
                {
                    "param_str": spec,
                    "recall_at_k": float(recall),
                    "latency_ms": float(latency_ms),
                }
            )
        profile = self._select_candidate(candidates)
        profile["refine_k_factor"] = float(
            refine_k_factor if refine_k_factor is not None else self._manager.refine_k_factor
        )
        meta = (
            self._manager._meta_snapshot()
        )  # lint-ignore[SLF001]: reuse internal helper for evaluation
        if "factory" in meta:
            profile["factory"] = meta["factory"]
        return profile

    @staticmethod
    def _select_candidate(rows: Sequence[dict[str, float | str]]) -> dict[str, Any]:
        if not rows:
            return {"param_str": "", "recall_at_k": 0.0, "latency_ms": float("inf")}
        ordered = sorted(
            rows,
            key=lambda row: (-float(row["recall_at_k"]), float(row["latency_ms"])),
        )
        best_recall = float(ordered[0]["recall_at_k"])
        pareto = [row for row in ordered if float(row["recall_at_k"]) >= best_recall - 0.005]
        pareto.sort(key=lambda row: float(row["latency_ms"]))
        profile = dict(pareto[0])
        for token in str(profile["param_str"]).split(","):
            key, sep, raw_value = token.partition("=")
            if not sep:
                continue
            try:
                profile[key.strip()] = float(raw_value)
            except ValueError:
                continue
        return profile


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
    """Enable direct map support on FAISS indexes when available.

    This function attempts to enable direct map support on FAISS indexes that
    support it (primarily IVF-family indexes). Direct maps enable efficient vector
    reconstruction by storing array-backed mappings from index positions to vectors.
    The function downcasts the index to a concrete type (if possible) and calls
    make_direct_map() if available. Failures are logged but do not raise exceptions,
    allowing the index to function without direct map support.

    Parameters
    ----------
    index : _faiss.Index
        FAISS index object to enable direct map support on. May be a base Index
        type or wrapper (IndexIDMap2, etc.). The function attempts to downcast
        to concrete types to access index-specific methods.

    Notes
    -----
    This function is called by _configure_direct_map() to enable vector reconstruction
    capabilities. Direct maps are required for reconstruct_batch() and _extract_all_vectors()
    operations. Not all index types support direct maps (e.g., Flat indexes don't
    need them). The function handles errors gracefully, logging debug messages when
    direct map setup fails. Time complexity: O(1) for method lookup, O(n) for direct
    map construction where n is the number of vectors (if supported). The function
    modifies the index object in-place and is not thread-safe if the index is being
    used concurrently.
    """
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


def _wrap_bool_contains(raw: Callable[[int], object]) -> Callable[[int], bool]:
    """Wrap a raw contains function that returns a boolean-like value.

    Parameters
    ----------
    raw : Callable[[int], object]
        Raw contains function that returns a boolean-like value (truthy/falsy).

    Returns
    -------
    Callable[[int], bool]
        Callable that returns ``True`` when ``raw`` reports membership.
    """

    def contains(id_val: int) -> bool:
        """Check if an ID value is contained in the wrapped collection.

        Parameters
        ----------
        id_val : int
            ID value to check for membership.

        Returns
        -------
        bool
            ``True`` if the ID is found, ``False`` otherwise. Returns ``False``
            if type coercion fails.
        """
        try:
            return bool(raw(int(id_val)))
        except (TypeError, ValueError):
            return False

    return contains


def _wrap_index_contains(raw: Callable[[int], object]) -> Callable[[int], bool]:
    """Wrap a raw contains function that returns an index position.

    Parameters
    ----------
    raw : Callable[[int], object]
        Raw contains function that returns an index position (non-negative int)
        when found, or a negative value/exception when not found.

    Returns
    -------
    Callable[[int], bool]
        Callable that returns ``True`` when ``raw`` returns a non-negative index.
    """

    def contains(id_val: int) -> bool:
        """Check if an ID value is contained in the wrapped collection.

        Parameters
        ----------
        id_val : int
            ID value to check for membership.

        Returns
        -------
        bool
            ``True`` if the ID is found (non-negative index), ``False`` otherwise.
            Returns ``False`` if type coercion fails or the index is negative.
        """
        try:
            result = raw(int(id_val))
        except (TypeError, ValueError):
            return False
        return _coerce_to_int(result) >= 0

    return contains


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


def _parse_tuning_overrides(profile: Mapping[str, Any]) -> _TuningOverrides:
    """Normalize raw profile payload into structured overrides.

    Parameters
    ----------
    profile : Mapping[str, Any]
        Raw tuning profile dictionary containing runtime parameter overrides.
        Expected keys include ``nprobe``, ``ef``, ``k_factor``, and ``quantizer``.

    Returns
    -------
    _TuningOverrides
        Structured overrides with coerced numeric values.

    """
    param_str = str(profile.get("param_str") or "").strip()
    k_factor = profile.get("k_factor") or profile.get("refine_k_factor")
    return _TuningOverrides(
        param_str=param_str,
        nprobe=_coerce_optional_int(profile.get("nprobe")),
        ef_search=_coerce_optional_int(profile.get("efSearch")),
        quantizer_ef_search=_coerce_optional_int(profile.get("quantizer_efSearch")),
        k_factor=_coerce_optional_float(k_factor),
    )


def _persist_tuning_profile(manager: FAISSManager, profile: Mapping[str, Any]) -> None:
    """Persist tuning metadata without interrupting the caller."""
    try:
        manager._save_tuning_profile(dict(profile))
    except OSError:  # pragma: no cover - best effort
        LOGGER.debug(
            "Unable to persist tuning profile",
            extra=_log_extra(path=str(manager.autotune_profile_path)),
        )
    manager._tuned_parameters = dict(profile)


def _get_compile_options() -> str:
    """Return FAISS compile options for readiness logs.

    Returns
    -------
    str
        Compile option string or ``"unknown"`` when unavailable.
    """
    get_opts = getattr(faiss, "get_compile_options", None)
    options = "unknown"
    if callable(get_opts):
        options = str(get_opts())
    set_compile_flags_id(options)
    return options


__all__ = ["AutoTuner", "FAISSManager", "apply_parameters"]
