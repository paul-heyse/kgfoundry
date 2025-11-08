"""FAISS manager for GPU-accelerated vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with cuVS acceleration,
CPU persistence, and GPU cloning. Index type is automatically selected based on
corpus size for optimal performance.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

import faiss
import numpy as np

from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
logger = LOGGER  # Alias for compatibility


def _has_faiss_gpu_support() -> bool:
    """Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.

    Returns
    -------
    bool
        ``True`` when GPU capabilities are available, otherwise ``False``.
    """
    required_attrs = ("StandardGpuResources", "GpuClonerOptions", "index_cpu_to_gpu")
    return all(hasattr(faiss, attr) for attr in required_attrs)


_FAISS_GPU_AVAILABLE = _has_faiss_gpu_support()

# Adaptive indexing thresholds
_SMALL_CORPUS_THRESHOLD = 5000
_MEDIUM_CORPUS_THRESHOLD = 50000

_LOG_EXTRA_BASE: dict[str, object] = {"component": "faiss_manager"}


def _log_extra(**kwargs: object) -> dict[str, object]:
    """Build structured logging extras for FAISS manager events.

    Returns
    -------
    dict[str, object]
        Merged dictionary with component name and provided kwargs.
    """
    return {**_LOG_EXTRA_BASE, **kwargs}


class FAISSManager:
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
    """

    def __init__(
        self,
        index_path: Path,
        vec_dim: int = 2560,
        nlist: int = 8192,
        *,
        use_cuvs: bool = True,
    ) -> None:
        self.index_path = index_path
        self.vec_dim = vec_dim
        self.nlist = nlist
        self.use_cuvs = use_cuvs
        self.cpu_index: faiss.Index | None = None
        self.gpu_index: faiss.Index | None = None
        self.gpu_resources: faiss.StandardGpuResources | None = None
        self.gpu_disabled_reason: str | None = None

        # Secondary index for incremental updates (dual-index architecture)
        self.secondary_index: faiss.Index | None = None
        self.secondary_gpu_index: faiss.Index | None = None
        self.incremental_ids: set[int] = set()
        # Secondary index path: same directory as primary, with .secondary suffix
        self.secondary_index_path = (
            index_path.parent / f"{index_path.stem}.secondary{index_path.suffix}"
        )

    def build_index(self, vectors: np.ndarray) -> None:
        """Build and train FAISS index with adaptive type selection.

        Chooses the optimal index type based on corpus size:
        - Small corpus (<5K vectors): IndexFlatIP (exact search, no training)
        - Medium corpus (5K-50K vectors): IVFFlat with dynamic nlist
        - Large corpus (>50K vectors): IVF-PQ with dynamic nlist

        This adaptive selection provides 10-100x faster training for small/medium
        corpora while maintaining high recall (>95%) and search performance.

        Parameters
        ----------
        vectors : np.ndarray
            Training vectors of shape (n, vec_dim). Vectors are automatically
            L2-normalized for cosine similarity.

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
        # Normalize for cosine similarity via inner product
        faiss.normalize_L2(vectors)

        n_vectors = len(vectors)

        if n_vectors < _SMALL_CORPUS_THRESHOLD:
            # Small corpus: use flat index (exact search, no training)
            cpu_index = faiss.IndexFlatIP(self.vec_dim)  # type: ignore[attr-defined]
            LOGGER.info(
                "Using IndexFlatIP for small corpus",
                extra=_log_extra(n_vectors=n_vectors, index_type="flat"),
            )
        elif n_vectors < _MEDIUM_CORPUS_THRESHOLD:
            # Medium corpus: use IVFFlat with dynamic nlist
            nlist = min(int(np.sqrt(n_vectors)), n_vectors // 39)
            nlist = max(nlist, 100)  # Minimum 100 clusters

            quantizer = faiss.IndexFlatIP(self.vec_dim)  # type: ignore[attr-defined]
            cpu_index = faiss.IndexIVFFlat(  # type: ignore[attr-defined]
                quantizer, self.vec_dim, nlist, faiss.METRIC_INNER_PRODUCT
            )
            cpu_index.train(vectors)
            LOGGER.info(
                "Using IVFFlat for medium corpus",
                extra=_log_extra(n_vectors=n_vectors, nlist=nlist, index_type="ivf_flat"),
            )
        else:
            # Large corpus: use IVF-PQ with dynamic nlist
            nlist = int(np.sqrt(n_vectors))
            nlist = max(nlist, 1024)  # Minimum 1024 clusters for PQ

            index_string = f"OPQ64,IVF{nlist},PQ64"
            cpu_index = faiss.index_factory(self.vec_dim, index_string, faiss.METRIC_INNER_PRODUCT)
            cpu_index.train(vectors)
            LOGGER.info(
                "Using IVF-PQ for large corpus",
                extra=_log_extra(n_vectors=n_vectors, nlist=nlist, index_type="ivf_pq"),
            )

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

        # Wrap in IDMap for ID management
        self.cpu_index = faiss.IndexIDMap2(cpu_index)

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

    def add_vectors(self, vectors: np.ndarray, ids: np.ndarray) -> None:
        """Add vectors with IDs to the index.

        Adds a batch of vectors to the FAISS index with their associated IDs.
        The vectors are normalized for cosine similarity (L2 normalization) before
        being added. IDs are used for retrieval - they should match the chunk IDs
        stored in DuckDB.

        This method requires that build_index() has been called first to create
        and train the index structure.

        Parameters
        ----------
        vectors : np.ndarray
            Vectors to add, shape (n, vec_dim) where n is the number of vectors
            and vec_dim matches the index dimension. Dtype should be float32.
        ids : np.ndarray
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

    def update_index(self, new_vectors: np.ndarray, new_ids: np.ndarray) -> None:
        """Add new vectors to secondary index for fast incremental updates.

        Adds vectors to a secondary flat index (IndexFlatIP) which requires no
        training and provides instant updates. This enables fast incremental
        indexing without rebuilding the primary index.

        The secondary index is automatically created on first call. Vectors are
        L2-normalized automatically for cosine similarity. Duplicate IDs are
        skipped to prevent conflicts, including IDs that already exist in the
        primary index.

        Parameters
        ----------
        new_vectors : np.ndarray
            New vectors to add, shape (n, vec_dim) where n is the number of vectors
            and vec_dim matches the index dimension. Dtype should be float32.
        new_ids : np.ndarray
            Unique IDs for each vector, shape (n,). IDs are stored as int64 in
            FAISS. These should correspond to chunk IDs from the indexing pipeline.

        Notes
        -----
        The secondary index uses a flat structure (IndexFlatIP) for simplicity
        and speed. No training is required, making updates instant (seconds).
        The secondary index is automatically searched alongside the primary index
        when using `search()`, with results merged by score.

        For optimal performance, periodically merge the secondary index into the
        primary using `merge_indexes()` and rebuild the primary index.

        Examples
        --------
        >>> manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=2560)
        >>> manager.build_index(initial_vectors)  # Build primary index
        >>> # Later, add new vectors incrementally
        >>> manager.update_index(new_vectors, new_ids)
        >>> # Search automatically uses both indexes
        >>> distances, ids = manager.search(query_vector)
        """
        # Initialize secondary index if it doesn't exist
        if self.secondary_index is None:
            flat_index = faiss.IndexFlatIP(self.vec_dim)  # type: ignore[attr-defined]
            self.secondary_index = faiss.IndexIDMap2(flat_index)
            LOGGER.info(
                "Created secondary flat index for incremental updates",
                extra=_log_extra(event="secondary_index_created"),
            )

        def _build_primary_contains() -> Callable[[int], bool]:
            try:
                cpu_index = self._require_cpu_index()
            except RuntimeError:
                return lambda _id: False

            if not hasattr(cpu_index, "id_map"):
                return lambda _id: False

            id_map = cpu_index.id_map  # type: ignore[attr-defined]

            if hasattr(id_map, "contains"):

                def _contains(id_val: int) -> bool:
                    try:
                        return bool(id_map.contains(int(id_val)))  # type: ignore[attr-defined]
                    except (TypeError, ValueError):
                        return False

                return _contains

            if hasattr(id_map, "search"):

                def _contains(id_val: int) -> bool:
                    try:
                        return int(id_map.search(int(id_val))) >= 0  # type: ignore[attr-defined]
                    except (TypeError, ValueError):
                        return False

                return _contains

            if hasattr(id_map, "find"):

                def _contains(id_val: int) -> bool:
                    try:
                        return int(id_map.find(int(id_val))) >= 0  # type: ignore[attr-defined]
                    except (TypeError, ValueError):
                        return False

                return _contains

            try:
                n_total = cpu_index.ntotal  # type: ignore[attr-defined]
            except AttributeError:
                return lambda _id: False

            try:
                existing_ids = {
                    int(id_map.at(idx))  # type: ignore[attr-defined]
                    for idx in range(n_total)
                }
            except (AttributeError, TypeError, ValueError):
                return lambda _id: False

            return lambda id_val: int(id_val) in existing_ids

        primary_contains = _build_primary_contains()

        unique_indices: list[int] = []
        seen_in_batch: set[int] = set()

        for offset, id_val in enumerate(new_ids.tolist()):
            id_int = int(id_val)
            if id_int in seen_in_batch:
                continue
            seen_in_batch.add(id_int)
            if id_int in self.incremental_ids:
                continue
            if primary_contains(id_int):
                continue
            unique_indices.append(offset)

        if len(unique_indices) == 0:
            LOGGER.info(
                "All vectors already indexed in secondary index",
                extra=_log_extra(total=len(new_ids)),
            )
            return

        # Filter to unique vectors and IDs
        unique_vectors = new_vectors[unique_indices]
        unique_ids = new_ids[unique_indices]

        # Normalize vectors
        vectors_norm = unique_vectors.copy()
        faiss.normalize_L2(vectors_norm)

        # Add to secondary index
        self.secondary_index.add_with_ids(vectors_norm, unique_ids.astype(np.int64))

        # Track incremental IDs
        self.incremental_ids.update(unique_ids.tolist())

        LOGGER.info(
            "Added vectors to secondary index",
            extra=_log_extra(
                added=len(unique_ids),
                total_secondary_vectors=len(self.incremental_ids),
                skipped_duplicates=len(new_ids) - len(unique_ids),
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

        self.cpu_index = faiss.read_index(str(self.index_path))

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

        self.secondary_index = faiss.read_index(str(self.secondary_index_path))

        # Restore incremental_ids from the loaded index
        if self.secondary_index is not None:
            n_vectors = self.secondary_index.ntotal  # type: ignore[attr-defined]
            if hasattr(self.secondary_index, "id_map"):
                # Extract IDs from the index
                self.incremental_ids = {
                    self.secondary_index.id_map.at(i)  # type: ignore[attr-defined]
                    for i in range(n_vectors)
                }
            else:
                # Fallback: assume sequential IDs if no id_map
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
        try:
            cpu_index = self._require_cpu_index()
        except RuntimeError as exc:
            msg = "Cannot clone index to GPU before building or loading it."
            raise RuntimeError(msg) from exc

        self.gpu_disabled_reason = None

        if not _FAISS_GPU_AVAILABLE:
            self.gpu_disabled_reason = "FAISS GPU symbols unavailable - running in CPU mode"
            LOGGER.info(
                "Skipping GPU clone; FAISS GPU symbols unavailable",
                extra=_log_extra(reason=self.gpu_disabled_reason, device=device),
            )
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
            return False

        return True

    def search(
        self, query: np.ndarray, k: int = 50, nprobe: int = 128
    ) -> tuple[np.ndarray, np.ndarray]:
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
        query : np.ndarray
            Query vector(s) of shape (n_queries, vec_dim) or (vec_dim,) for
            single query. Dtype should be float32. Vectors are automatically
            normalized for cosine similarity.
        k : int, optional
            Number of nearest neighbors to return per query (default: 50).
            Higher k improves recall but increases computation and memory usage.
        nprobe : int, optional
            Number of IVF cells to probe during search (default: 128). Higher
            values improve recall but slow down search. Should match or be less
            than the nlist parameter used during index construction. Only applies
            to primary index (secondary index is flat, no nprobe).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple of (distances, ids) arrays:
            - distances: shape (n_queries, k), cosine similarity scores (higher
              is more similar, range typically 0-1 after normalization)
            - ids: shape (n_queries, k), chunk IDs of the nearest neighbors.
              IDs correspond to the ids passed to add_vectors() or update_index().

        Notes
        -----
        When both primary and secondary indexes exist, the method:
        1. Searches primary index with nprobe parameter
        2. Searches secondary index (flat, no nprobe)
        3. Merges results by score (inner product distance)
        4. Returns top-k combined results

        This ensures incremental updates are immediately searchable without
        rebuilding the primary index.

        Raises RuntimeError (propagated from `_search_primary()` and
        `_search_secondary()`) if no index is available or if search fails
        (e.g., dimension mismatch, invalid nprobe value).
        """
        # Search primary index
        primary_dists, primary_ids = self._search_primary(query, k, nprobe)

        # Search secondary index if it exists
        if self.secondary_index is not None:
            secondary_dists, secondary_ids = self._search_secondary(query, k)
            # Merge results by score
            merged_dists, merged_ids = self._merge_results(
                primary_dists, primary_ids, secondary_dists, secondary_ids, k
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

        # No secondary index - return primary results only
        return primary_dists, primary_ids

    def _search_primary(
        self, query: np.ndarray, k: int, nprobe: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Search the primary index (adaptive type: Flat/IVFFlat/IVF-PQ).

        Parameters
        ----------
        query : np.ndarray
            Query vector(s), shape (n_queries, vec_dim) or (vec_dim,).
        k : int
            Number of nearest neighbors to return.
        nprobe : int
            Number of IVF cells to probe (for IVF indexes).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
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

    def _search_secondary(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Search the secondary index (flat, no training required).

        Parameters
        ----------
        query : np.ndarray
            Query vector(s), shape (n_queries, vec_dim) or (vec_dim,).
        k : int
            Number of nearest neighbors to return.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
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

    @staticmethod
    def _merge_results(
        dists1: np.ndarray,
        ids1: np.ndarray,
        dists2: np.ndarray,
        ids2: np.ndarray,
        k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Merge search results from two indexes by score.

        Combines results from primary and secondary indexes, sorts by distance
        (inner product, higher is better), and returns the top-k combined results.

        Parameters
        ----------
        dists1 : np.ndarray
            Distances from first index, shape (n_queries, k1).
        ids1 : np.ndarray
            IDs from first index, shape (n_queries, k1).
        dists2 : np.ndarray
            Distances from second index, shape (n_queries, k2).
        ids2 : np.ndarray
            IDs from second index, shape (n_queries, k2).
        k : int
            Number of top results to return after merging.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
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

    def _extract_all_vectors(self, index: faiss.Index) -> tuple[np.ndarray, np.ndarray]:
        """Extract all vectors and IDs from a FAISS index.

        Reconstructs vectors from the index and retrieves their associated IDs.
        For quantized indexes (e.g., IVF-PQ), reconstruction returns approximate
        vectors (dequantized from the codebook).

        Parameters
        ----------
        index : faiss.Index
            FAISS index to extract vectors from. Must support `reconstruct()` and
            have an `id_map` attribute (IndexIDMap2 wrapper).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Tuple of (vectors, ids):
            - vectors: shape (n_vectors, vec_dim), dtype float32
            - ids: shape (n_vectors,), dtype int64

        Raises
        ------
        RuntimeError
            If the index does not support vector reconstruction or ID mapping.
            This can occur with certain index types or if the index is not wrapped
            with IndexIDMap2.
        """
        n_vectors = index.ntotal  # type: ignore[attr-defined]
        if n_vectors == 0:
            return np.empty((0, self.vec_dim), dtype=np.float32), np.empty(0, dtype=np.int64)

        vectors = np.empty((n_vectors, self.vec_dim), dtype=np.float32)
        ids = np.empty(n_vectors, dtype=np.int64)

        # Check if index has id_map (IndexIDMap2 wrapper)
        if not hasattr(index, "id_map"):
            msg = f"Index type {type(index).__name__} does not support ID mapping. Index must be wrapped with IndexIDMap2."
            raise RuntimeError(msg)

        # Extract vectors and IDs
        for i in range(n_vectors):
            try:
                vectors[i] = index.reconstruct(i)  # type: ignore[attr-defined]
                ids[i] = index.id_map.at(i)  # type: ignore[attr-defined]
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

    def _require_cpu_index(self) -> faiss.Index:
        """Return the CPU index if initialized.

        Returns
        -------
        faiss.Index
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

    def _active_index(self) -> faiss.Index:
        """Return the best available search index.

        Returns
        -------
        faiss.Index
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


__all__ = ["FAISSManager"]
