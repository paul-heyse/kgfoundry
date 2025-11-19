"""FAISS manager for CPU vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with CPU persistence.
Index type is automatically selected based on corpus size for optimal performance.

This is a thin facade that delegates to specialized modules:
- faiss_build: Index construction and lifecycle
- faiss_runtime: Query execution and runtime tuning
- faiss_store: Persistence and metadata management
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.errors import VectorIndexStateError
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    IndexFamily,
    build_primary_index,
    choose_family,
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
    save_index as builder_save_index,
)
from codeintel_rev.io.faiss_runtime import (
    FAISSRuntimeOptions,
    SearchRuntimeOverrides,
    apply_runtime_parameters,
    brute_force_truth_ids,
    ensure_2d,
    estimate_recall,
    timed_search_with_params,
)
from codeintel_rev.io.faiss_runtime import (
    RefineSearchConfig as _RefineSearchConfig,
)
from codeintel_rev.io.faiss_runtime import (
    search_dual as runtime_search_dual,
)
from codeintel_rev.io.faiss_store import (
    IndexArtifactPaths,
    export_idmap_parquet,
    get_idmap_array,
    load_tuned_profile,
    save_tuning_profile,
    write_meta_snapshot,
)
from codeintel_rev.io.faiss_store import (
    load_secondary_index as store_load_secondary,
)
from codeintel_rev.io.faiss_store import (
    reconstruct_batch as store_reconstruct_batch,
)
from codeintel_rev.io.faiss_store import (
    save_secondary_index as store_save_secondary,
)
from codeintel_rev.retrieval.types import SearchHit
from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64

if TYPE_CHECKING:
    import numpy as np

    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
else:  # pragma: no cover - lazy runtime imports
    np = cast("np", LazyModule("numpy", "FAISS manager vector operations"))
    DuckDBCatalog = Any

RefineSearchConfig = _RefineSearchConfig

# Lazy FAISS module
_faiss = LazyModule("faiss", "FAISS manager operations")
faiss = cast("Any", _faiss)

_DEFAULT_SWEEP = ("nprobe=16", "nprobe=32", "nprobe=64", "nprobe=96", "nprobe=128")
_IVFFLAT_BALANCE_DIVISOR = 39


class _RuntimeFacade:
    """Runtime tuning adapter exposed via :class:`FAISSManager.runtime`."""

    def __init__(
        self,
        *,
        describe: Callable[[], dict[str, object]],
        apply: Callable[[dict[str, object]], dict[str, object]],
        reset: Callable[[], dict[str, object]],
        set_params: Callable[[str], dict[str, object]],
    ) -> None:
        """Initialize runtime facade with dependency injection callables.

        Parameters
        ----------
        describe : Callable[[], dict[str, object]]
            Function that returns current runtime tuning state and metadata.
        apply : Callable[[dict[str, object]], dict[str, object]]
            Function that applies runtime tuning parameters and returns updated state.
        reset : Callable[[], dict[str, object]]
            Function that resets runtime tuning to defaults and returns state.
        set_params : Callable[[str], dict[str, object]]
            Function that sets runtime parameters from a JSON string and returns state.
        """
        self._describe = describe
        self._apply = apply
        self._reset = reset
        self._set_params = set_params

    def get_runtime_tuning(self) -> dict[str, object]:
        """Return active runtime parameters, overrides, and profile metadata.

        Returns
        -------
        dict[str, object]
            Runtime tuning snapshot including active values and overrides.
        """
        return self._describe()

    def apply_runtime_tuning(
        self,
        *,
        nprobe: int | None = None,
        ef_search: int | None = None,
        quantizer_ef_search: int | None = None,
        k_factor: float | None = None,
    ) -> dict[str, object]:
        """Apply runtime overrides to the active FAISS index.

        Parameters
        ----------
        nprobe : int | None, optional
            Number of clusters to probe in IVF indexes. None means use defaults.
            Defaults to None.
        ef_search : int | None, optional
            HNSW ef_search parameter override. None means use defaults.
            Defaults to None.
        quantizer_ef_search : int | None, optional
            Quantizer ef_search parameter override. None means use defaults.
            Defaults to None.
        k_factor : float | None, optional
            K factor override for search refinement. None means use defaults.
            Defaults to None.

        Returns
        -------
        dict[str, object]
            Updated runtime tuning snapshot after applying overrides.
        """
        overrides: dict[str, object] = {}
        if nprobe is not None:
            overrides["nprobe"] = nprobe
        if ef_search is not None:
            overrides["efSearch"] = ef_search
        if quantizer_ef_search is not None:
            overrides["quantizer_efSearch"] = quantizer_ef_search
        if k_factor is not None:
            overrides["k_factor"] = k_factor
        return self._apply(overrides)

    def reset_runtime_tuning(self) -> dict[str, object]:
        """Clear runtime overrides and revert to defaults.

        Returns
        -------
        dict[str, object]
            Runtime tuning snapshot after reset.
        """
        return self._reset()

    def set_search_parameters(self, param_str: str) -> dict[str, object]:
        """Apply FAISS ParameterSpace string (``nprobe=32,efSearch=64``).

        Parameters
        ----------
        param_str : str
            FAISS ParameterSpace string (e.g., "nprobe=32,efSearch=64").

        Returns
        -------
        dict[str, object]
            Runtime tuning snapshot after applying the parameter string.
        """
        return self._set_params(param_str)


class FAISSManager:
    """FAISS index manager with adaptive indexing and incremental updates."""

    _PARAMETER_ALIASES: ClassVar[dict[str, str]] = {
        "nprobe": "nprobe",
        "efsearch": "efSearch",
        "ef_search": "efSearch",
        "efSearch": "efSearch",
        "quantizer_efsearch": "quantizer_efSearch",
        "quantizer_ef_search": "quantizer_efSearch",
        "quantizer_efSearch": "quantizer_efSearch",
        "k_factor": "k_factor",
        "kfactor": "k_factor",
        "kFactor": "k_factor",
    }

    def __init__(
        self,
        index_path: Path,
        vec_dim: int = 3584,
        nlist: int = 8192,
        *,
        runtime: FAISSRuntimeOptions | None = None,
    ) -> None:
        """Initialize FAISS manager state and runtime configuration."""
        self.index_path = Path(index_path)
        self.vec_dim = vec_dim
        self.nlist = nlist

        opts = runtime or FAISSRuntimeOptions()
        self.runtime_opts = opts
        self.default_k = opts.default_k
        self.default_nprobe = opts.default_nprobe or 128
        self.hnsw_ef_search = opts.hnsw_ef_search
        self.refine_k_factor = opts.refine_k_factor
        self.autotune_on_start = opts.autotune_on_start
        self.faiss_family: str | None = opts.faiss_family

        # Live indexes
        self.cpu_index: FaissIndex | None = None
        self.secondary_index: FaissIndex | None = None
        self.incremental_ids: set[int] = set()
        self._primary_ids: set[int] = set()

        # Runtime state
        self._runtime_overrides: dict[str, float] = {}
        self._tuning_lock = RLock()
        self._paths = IndexArtifactPaths(self.index_path)
        self.autotune_profile_path = self.index_path.with_name("tuning.json")
        self._legacy_autotune_profile_path = self.index_path.with_suffix(".tune.json")
        self._meta_path = Path(f"{self.index_path}.meta.json")
        self._vector_count: int | None = None
        self._faiss_factory: str | None = None
        self._parameter_space: str | None = None
        self._default_refine_k_factor = self.refine_k_factor
        self._runtime_facade = _RuntimeFacade(
            describe=self._describe_runtime_state,
            apply=self._apply_runtime_overrides_public,
            reset=self._reset_runtime_overrides_public,
            set_params=self._set_parameter_string_public,
        )

    def build_index(self, vectors: NDArrayF32, *, family: str | None = None) -> None:
        """Build and train FAISS index with adaptive type selection.

        Parameters
        ----------
        vectors : NDArrayF32
            Vector array to build the index from. Shape should be (n_vectors, vec_dim).
        family : str | None, optional
            Index family identifier ("ivf", "hnsw", "adaptive"). None means use
            "adaptive". Defaults to None.

        Raises
        ------
        VectorIndexStateError
            If vectors is None or empty.
        """
        if vectors is None or vectors.size == 0:
            msg = "vectors must be a non-empty array"
            raise VectorIndexStateError(msg)

        resolved_family: IndexFamily = cast("IndexFamily", family or "adaptive")
        cfg = IndexBuildConfig(
            vec_dim=self.vec_dim,
            default_nlist=self.nlist,
            family=resolved_family,
        )
        index, factory = build_primary_index(vectors, cfg=cfg, override_family=resolved_family)
        self.cpu_index = index
        self.secondary_index = None
        self.incremental_ids.clear()
        self._primary_ids.clear()
        self.faiss_family = resolved_family
        self._faiss_factory = factory
        self._vector_count = int(vectors.shape[0])
        self._write_meta_snapshot(vector_count=self._vector_count, factory=factory)

    def add_vectors(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """Add vectors to the primary index after build.

        Parameters
        ----------
        vectors : NDArrayF32
            Vector array to add. Shape should be (n_vectors, vec_dim).
        ids : NDArrayI64
            Chunk ID array corresponding to vectors. Shape should be (n_vectors,).

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized; call build_index() first."
            raise RuntimeError(msg)
        builder_add_vectors(self.cpu_index, vectors, ids)
        self._primary_ids.update(int(cid) for cid in np.asarray(ids, dtype=np.int64).reshape(-1))

    def update_index(self, new_vectors: NDArrayF32, new_ids: NDArrayI64) -> int:
        """Add vectors to the secondary (incremental) index.

        Parameters
        ----------
        new_vectors : NDArrayF32
            Vector array to add. Shape should be (n_vectors, vec_dim).
        new_ids : NDArrayI64
            Chunk ID array corresponding to vectors. Shape should be (n_vectors,).

        Returns
        -------
        int
            Number of vectors successfully added (after deduplication).

        Raises
        ------
        RuntimeError
            If primary index is not initialized or secondary index creation fails.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized. Run build_index() or load_cpu_index() first."
            raise RuntimeError(msg)

        self._ensure_secondary()
        self._ensure_primary_ids()

        ids_arr = np.asarray(new_ids, dtype=np.int64).reshape(-1)
        vectors_arr = np.asarray(new_vectors, dtype=np.float32)
        keep_mask = np.ones_like(ids_arr, dtype=bool)
        seen = set()

        for pos, cid in enumerate(ids_arr.tolist()):
            if cid in seen or cid in self.incremental_ids or cid in self._primary_ids:
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
            self._persist_incremental_ids()

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

    def load_cpu_index(
        self,
        *,
        export_idmap: Path | None = None,
        profile_path: Path | None = None,
    ) -> None:
        """Load the primary CPU index from disk and apply persisted tuning."""
        self.cpu_index = builder_load_index(self.index_path)
        self.secondary_index = None
        self.incremental_ids.clear()
        self._refresh_primary_ids()
        self.faiss_family = self.runtime_opts.faiss_family
        if export_idmap is not None:
            self.export_idmap(export_idmap)
        self._sync_runtime_from_meta()
        profile = self._load_profile_payload(profile_path or self._resolve_profile_to_read())
        if profile is not None:
            self._apply_profile_payload(profile)
        elif self._runtime_overrides:
            self._apply_runtime_overrides(self._runtime_overrides, persist=False)

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
        self._persist_incremental_ids()

    def load_secondary_index(self) -> None:
        """Load the secondary index from disk (.secondary suffix)."""
        try:
            self.secondary_index = store_load_secondary(self._paths)
            self._load_incremental_ids()
        except FileNotFoundError:
            self.secondary_index = None
            self.incremental_ids.clear()
            self._persist_incremental_ids()

    def export_idmap(self, out_path: Path) -> int:
        """Export {faiss_row -> external_id} mapping to Parquet.

        Parameters
        ----------
        out_path : Path
            Output file path for the Parquet ID map.

        Returns
        -------
        int
            Number of ID mappings exported.

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return export_idmap_parquet(
            self.cpu_index,
            out_path,
            index_name=self.index_path.name,
        )

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
            Query vector. Shape should be (vec_dim,) or (1, vec_dim).
        k : int | None, optional
            Number of nearest neighbors to retrieve. None means use default_k.
            Defaults to None.
        nprobe : int | None, optional
            Number of clusters to probe in IVF indexes. None means use default_nprobe.
            Defaults to None.
        runtime : SearchRuntimeOverrides | None, optional
            Optional runtime override parameters. None means use defaults.
            Defaults to None.
        catalog : object | None, optional
            Optional DuckDB catalog for exact reranking. None means skip reranking.
            Defaults to None.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (distances, ids) arrays from the search.

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
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

    def search_with_refine(
        self,
        query: NDArrayF32,
        *,
        k: int,
        catalog: DuckDBCatalog,
        config: RefineSearchConfig | None = None,
    ) -> list[SearchHit]:
        """Execute ANN search and return structured :class:`SearchHit` rows.

        Parameters
        ----------
        query : NDArrayF32
            Query vector. Shape should be (vec_dim,) or (1, vec_dim).
        k : int
            Number of nearest neighbors to retrieve. Must be positive.
        catalog : DuckDBCatalog
            DuckDB catalog for hydrating search results with metadata.
        config : RefineSearchConfig | None, optional
            Optional refinement configuration. None means use defaults.
            Defaults to None.

        Returns
        -------
        list[SearchHit]
            List of search hits with scores, ranks, and explanation metadata.
        """
        cfg = config or RefineSearchConfig()
        distances, ids = self.search(
            query=query,
            k=k,
            nprobe=cfg.nprobe,
            runtime=cfg.runtime,
            catalog=catalog,
        )
        if distances.size == 0:
            return []
        k_factor = (
            cfg.runtime.k_factor
            if cfg.runtime and cfg.runtime.k_factor is not None
            else self.refine_k_factor
        )
        nprobe = cfg.nprobe or self._runtime_overrides.get("nprobe") or self.default_nprobe
        hits: list[SearchHit] = []
        for rank, (score, chunk_id) in enumerate(zip(distances[0], ids[0], strict=False)):
            if int(chunk_id) < 0:
                continue
            explain = {
                "k_factor": float(k_factor),
                "nprobe": int(nprobe) if nprobe is not None else None,
            }
            hits.append(
                SearchHit(
                    doc_id=str(int(chunk_id)),
                    rank=rank,
                    score=float(score),
                    source=cfg.source,
                    faiss_row=None,
                    explain=explain,
                )
            )
        return hits

    def apply_runtime_parameters(self, overrides: dict[str, float | int]) -> None:
        """Apply runtime parameter overrides to the active index."""
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

        Raises
        ------
        RuntimeError
            If primary index is not initialized.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        if self.secondary_index is None:
            return

        ids = get_idmap_array(self.secondary_index)
        if ids.size == 0:
            self.secondary_index = None
            self.incremental_ids.clear()
            self._persist_incremental_ids()
            return

        candidate_ids = np.asarray(ids, dtype=np.int64).reshape(-1)
        self._ensure_primary_ids()
        keep_mask = np.array([cid not in self._primary_ids for cid in candidate_ids], dtype=bool)
        if not keep_mask.any():
            self.secondary_index = None
            self.incremental_ids.clear()
            self._persist_incremental_ids()
            return

        vectors = store_reconstruct_batch(
            self.secondary_index,
            self.vec_dim,
            candidate_ids.tolist(),
        )
        builder_add_vectors(self.cpu_index, vectors[keep_mask], candidate_ids[keep_mask])
        self._primary_ids.update(int(cid) for cid in candidate_ids[keep_mask])

        self.secondary_index = None
        self.incremental_ids.clear()
        self._persist_incremental_ids()

    def require_cpu_index(self) -> FaissIndex:
        """Get the primary CPU index or raise if not initialized.

        Returns
        -------
        FaissIndex
            The primary CPU index.

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
        """Get the currently active index (primary or secondary).

        Returns
        -------
        FaissIndex
            The active index (primary preferred, falls back to secondary).

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
    def runtime(self) -> _RuntimeFacade:
        """Expose runtime tuning helpers (GET/POST /tuning/faiss)."""
        return self._runtime_facade

    @property
    def tuning_lock(self) -> RLock:
        """Lock for runtime tuning mutations."""
        return self._tuning_lock

    @property
    def runtime_overrides(self) -> dict[str, float]:
        """Mutable runtime override dictionary."""
        return self._runtime_overrides

    def autotune(
        self,
        queries: NDArrayF32,
        truths: NDArrayF32,
        *,
        k: int = 10,
        sweep: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Sweep ParameterSpace strings and persist the best profile.

        Parameters
        ----------
        queries : NDArrayF32
            Query vectors array. Shape should be (n_queries, vec_dim).
        truths : NDArrayF32
            Ground truth vectors array. Shape should be (n_truths, vec_dim).
        k : int, optional
            Number of nearest neighbors to evaluate. Must be positive.
            Defaults to 10.
        sweep : Sequence[str] | None, optional
            Optional sequence of ParameterSpace strings to evaluate. None means
            use default sweep. Defaults to None.

        Returns
        -------
        dict[str, object]
            Best autotune profile dictionary with parameters and metrics.

        Raises
        ------
        RuntimeError
            If primary index is not initialized or sweep evaluation fails.
        ValueError
            If sweep parameters are invalid.
        """
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        params = tuple(sweep or _DEFAULT_SWEEP)
        if not params:
            msg = "Sweep list must contain at least one parameter string"
            raise ValueError(msg)

        queries_arr = ensure_2d(np.asarray(queries, dtype=np.float32))
        truths_arr = ensure_2d(np.asarray(truths, dtype=np.float32))
        truth_ids = brute_force_truth_ids(queries_arr, truths_arr, k)

        best_profile: dict[str, object] | None = None
        best_recall = float("-inf")
        best_latency = float("inf")

        for param_str in params:
            latency_ms, (_, cand_ids) = timed_search_with_params(
                self.require_cpu_index(),
                queries_arr,
                k,
                param_str,
            )
            recall = estimate_recall(cand_ids, truth_ids)
            if recall > best_recall or (recall == best_recall and latency_ms < best_latency):
                profile = self._build_autotune_profile(
                    param_str=param_str,
                    recall=recall,
                    latency_ms=latency_ms,
                    k=k,
                )
                best_profile = profile
                best_recall = recall
                best_latency = latency_ms

        if best_profile is None:
            msg = "Unable to evaluate sweep"
            raise RuntimeError(msg)

        save_tuning_profile(best_profile, self.autotune_profile_path)
        self._apply_profile_payload(best_profile)
        return best_profile

    def estimate_memory_usage(self, n_vectors: int) -> dict[str, int]:
        """Estimate memory usage in bytes for a given number of vectors.

        Parameters
        ----------
        n_vectors : int
            Number of vectors to estimate memory for. Must be positive.

        Returns
        -------
        dict[str, int]
            Dictionary with 'cpu_index_bytes' and 'total_bytes' estimates.
        """
        if n_vectors <= 0:
            return {"cpu_index_bytes": 0, "total_bytes": 0}
        cfg = IndexBuildConfig(
            vec_dim=self.vec_dim,
            default_nlist=self.nlist,
            family=self._resolve_family_hint(),
            pq_m=self.runtime_opts.pq_m,
            pq_bits=self.runtime_opts.pq_nbits,
            opq_m=self.runtime_opts.opq_m,
            hnsw_m=self.runtime_opts.hnsw_m,
        )
        family = choose_family(n_vectors, cfg)
        if family == "flat":
            cpu_bytes = n_vectors * self.vec_dim * 4
        elif family == "ivfflat":
            sqrt_n = int(np.sqrt(n_vectors))
            alt = (
                n_vectors // _IVFFLAT_BALANCE_DIVISOR
                if n_vectors >= _IVFFLAT_BALANCE_DIVISOR
                else sqrt_n
            )
            nlist = max(100, min(sqrt_n, alt))
            cpu_bytes = (nlist * self.vec_dim * 4) + (n_vectors * 8)
        else:
            nlist = max(1024, int(np.sqrt(n_vectors)))
            code_bytes = self.runtime_opts.pq_m * max(1, self.runtime_opts.pq_nbits // 8)
            cpu_bytes = (nlist * self.vec_dim * 4) + (n_vectors * code_bytes)
        return {
            "cpu_index_bytes": int(cpu_bytes),
            "total_bytes": int(cpu_bytes),
        }

    def _resolve_family_hint(self) -> IndexFamily:
        """Return the configured family hint, normalizing ``auto`` to adaptive.

        Returns
        -------
        IndexFamily
            Family literal representing the configured runtime hint.
        """
        hint = (self.runtime_opts.faiss_family or "adaptive").lower()
        if hint in {"auto", "adaptive"}:
            return "adaptive"
        if hint in {"flat", "ivfflat", "ivfpq"}:
            return cast("IndexFamily", hint)
        return "adaptive"

    def _write_meta_snapshot(
        self,
        *,
        vector_count: int | None = None,
        factory: str | None = None,
        parameter_space: str | None = None,
    ) -> None:
        """Write metadata snapshot file for the FAISS index.

        Parameters
        ----------
        vector_count : int | None, optional
            Override vector count, otherwise uses manager's count.
        factory : str | None, optional
            Override FAISS factory string, otherwise uses manager's factory.
        parameter_space : str | None, optional
            Override parameter space description, otherwise uses manager's space.
        """
        write_meta_snapshot(
            index_path=self.index_path,
            vec_dim=self.vec_dim,
            faiss_family=self.runtime_opts.faiss_family,
            default_nprobe=self.default_nprobe,
            hnsw_ef_search=self.hnsw_ef_search,
            refine_k_factor=self.refine_k_factor,
            meta_path=self._meta_path,
            runtime_overrides=self._runtime_overrides,
            factory=factory or self._faiss_factory,
            vector_count=vector_count or self._vector_count,
            parameter_space=parameter_space or self._parameter_space,
        )

    def _secondary_ids_path(self) -> Path:
        """Return path to secondary index IDs JSON file.

        Returns
        -------
        Path
            Path to IDs JSON file alongside secondary index.
        """
        secondary_path = self._paths.secondary_index_path
        return secondary_path.with_suffix(".ids.json")

    def _persist_incremental_ids(self) -> None:
        """Persist incremental IDs set to JSON file, or delete file if empty."""
        path = self._secondary_ids_path()
        if not self.incremental_ids:
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(self.incremental_ids)), encoding="utf-8")

    def _load_incremental_ids(self) -> None:
        """Load incremental IDs set from JSON file, clearing if file missing or invalid."""
        path = self._secondary_ids_path()
        if not path.exists():
            self.incremental_ids.clear()
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.incremental_ids.clear()
            return
        self.incremental_ids = {int(value) for value in payload}

    def _ensure_primary_ids(self) -> None:
        """Ensure primary IDs set is populated from CPU index if needed."""
        if self.cpu_index is None:
            self._primary_ids.clear()
            return
        if not self._primary_ids and int(getattr(self.cpu_index, "ntotal", 0)) > 0:
            self._refresh_primary_ids()

    def _refresh_primary_ids(self) -> None:
        """Refresh primary IDs set from CPU index ID map array."""
        if self.cpu_index is None:
            self._primary_ids.clear()
            return
        try:
            ids = get_idmap_array(self.cpu_index)
        except (RuntimeError, TypeError):
            self._primary_ids.clear()
            return
        self._primary_ids = {int(value) for value in ids.tolist()}

    def _resolve_profile_to_read(self) -> Path | None:
        """Resolve path to autotune profile file, checking current and legacy locations.

        Returns
        -------
        Path | None
            Path to existing profile file, or None if neither location exists.
        """
        for path in (self.autotune_profile_path, self._legacy_autotune_profile_path):
            if path and Path(path).exists():
                return Path(path)
        return None

    @staticmethod
    def _load_profile_payload(path: Path | None) -> dict[str, object] | None:
        """Load autotune profile payload from file.

        Parameters
        ----------
        path : Path | None
            Path to profile file, or None to skip loading.

        Returns
        -------
        dict[str, object] | None
            Profile dictionary if path exists, None otherwise.
        """
        if path is None:
            return None
        return load_tuned_profile(Path(path))

    def _apply_profile_payload(
        self,
        payload: Mapping[str, object],
        *,
        persist: bool = True,
    ) -> None:
        """Apply autotune profile payload to runtime overrides.

        Parameters
        ----------
        payload : Mapping[str, object]
            Profile dictionary containing runtime parameter overrides.
        persist : bool, optional
            Whether to persist changes to metadata snapshot. Defaults to True.
        """
        overrides = self._normalize_runtime_payload(
            nprobe=payload.get("nprobe"),
            ef_search=payload.get("efSearch"),
            quantizer_ef_search=payload.get("quantizer_efSearch"),
            k_factor=payload.get("k_factor") or payload.get("refine_k_factor"),
        )
        param_str = payload.get("param_str")
        normalized = str(param_str).strip() if isinstance(param_str, str) else None
        self._apply_runtime_overrides(overrides, parameter_space=normalized, persist=persist)
        factory = payload.get("factory")
        if isinstance(factory, str):
            self._faiss_factory = factory
            if persist:
                self._write_meta_snapshot(factory=factory)

    def _sync_runtime_from_meta(self) -> None:
        """Synchronize runtime overrides and factory from metadata file."""
        if not self._meta_path.exists():
            return
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        runtime_overrides = meta.get("runtime_overrides")
        if isinstance(runtime_overrides, Mapping):
            self._runtime_overrides = {
                key: float(value)
                for key, value in runtime_overrides.items()
                if isinstance(value, (int, float))
            }
        self._faiss_factory = cast("str | None", meta.get("factory"))
        self._vector_count = cast("int | None", meta.get("vector_count"))
        parameter_space = meta.get("parameter_space")
        if isinstance(parameter_space, str):
            self._parameter_space = parameter_space

    def _describe_runtime_state(self) -> dict[str, object]:
        """Describe current runtime state including active parameters and overrides.

        Returns
        -------
        dict[str, object]
            Dictionary containing active parameters, overrides, autotune profile,
            and parameter space if available.
        """
        profile = self._load_profile_payload(self._resolve_profile_to_read())
        snapshot = self._current_runtime_parameters()
        payload: dict[str, object] = {
            "active": snapshot,
            "overrides": dict(self._runtime_overrides),
        }
        if profile is not None:
            payload["autotune_profile"] = profile
        if self._parameter_space is not None:
            payload["parameter_space"] = self._parameter_space
        return payload

    def _apply_runtime_overrides_public(self, overrides: Mapping[str, object]) -> dict[str, object]:
        """Apply runtime overrides and return updated state description.

        Parameters
        ----------
        overrides : Mapping[str, object]
            Override values for nprobe, efSearch, quantizer_efSearch, k_factor.

        Returns
        -------
        dict[str, object]
            Updated runtime state description.

        Raises
        ------
        ValueError
            If no valid overrides are provided.
        """
        normalized = self._normalize_runtime_payload(
            nprobe=overrides.get("nprobe"),
            ef_search=overrides.get("efSearch"),
            quantizer_ef_search=overrides.get("quantizer_efSearch"),
            k_factor=overrides.get("k_factor"),
        )
        if not normalized:
            msg = "No overrides provided"
            raise ValueError(msg)
        self._apply_runtime_overrides(normalized)
        return self._describe_runtime_state()

    def _reset_runtime_overrides_public(self) -> dict[str, object]:
        """Reset runtime overrides to defaults and return updated state description.

        Returns
        -------
        dict[str, object]
            Updated runtime state description after reset.
        """
        self._reset_runtime_overrides()
        return self._describe_runtime_state()

    def _set_parameter_string_public(self, param_str: str) -> dict[str, object]:
        """Parse parameter string, apply overrides, and return updated state.

        Parameters
        ----------
        param_str : str
            Parameter string in format "key=value,key2=value2".

        Returns
        -------
        dict[str, object]
            Updated runtime state description.

        """
        overrides, normalized = self._parse_parameter_string(param_str)
        self._apply_runtime_overrides(overrides, parameter_space=normalized)
        return self._describe_runtime_state()

    def _current_runtime_parameters(self) -> dict[str, object]:
        """Get current runtime parameter values with overrides applied.

        Returns
        -------
        dict[str, object]
            Dictionary of current parameter values (nprobe, efSearch,
            quantizer_efSearch, k_factor).
        """
        return {
            "nprobe": self._runtime_overrides.get("nprobe", self.default_nprobe),
            "efSearch": self._runtime_overrides.get("efSearch", self.hnsw_ef_search),
            "quantizer_efSearch": self._runtime_overrides.get("quantizer_efSearch"),
            "k_factor": self._runtime_overrides.get("k_factor", self.refine_k_factor),
        }

    def _build_autotune_profile(
        self,
        *,
        param_str: str,
        recall: float,
        latency_ms: float,
        k: int,
    ) -> dict[str, object]:
        """Compose the persisted profile metadata for an autotune candidate.

        Parameters
        ----------
        param_str : str
            Parameter string evaluated during autotune sweep.
        recall : float
            Recall@k metric achieved with this parameter configuration.
        latency_ms : float
            Average search latency in milliseconds for this configuration.
        k : int
            Number of nearest neighbors evaluated. Must be positive.

        Returns
        -------
        dict[str, object]
            Profile dictionary persisted to disk for the candidate sweep value.
        """
        overrides, normalized = self._parse_parameter_string(param_str)
        profile: dict[str, object] = {
            "param_str": normalized,
            "recall_at_k": recall,
            "latency_ms": latency_ms,
            "k": k,
            "timestamp": datetime.now(UTC).isoformat(),
            "refine_k_factor": self.refine_k_factor,
        }
        profile.update(dict(overrides))
        return profile

    def _normalize_runtime_payload(
        self,
        *,
        nprobe: object | None = None,
        ef_search: object | None = None,
        quantizer_ef_search: object | None = None,
        k_factor: object | None = None,
    ) -> dict[str, float]:
        """Normalize runtime parameter values to typed float dictionary.

        Parameters
        ----------
        nprobe : object | None, optional
            Number of probes override value.
        ef_search : object | None, optional
            HNSW ef_search override value.
        quantizer_ef_search : object | None, optional
            Quantizer ef_search override value.
        k_factor : object | None, optional
            Refinement k_factor override value.

        Returns
        -------
        dict[str, float]
            Normalized overrides dictionary with only non-None values included.

        """
        overrides: dict[str, float] = {}
        if nprobe is not None:
            overrides["nprobe"] = float(self._coerce_positive_int(nprobe, "nprobe"))
        if ef_search is not None:
            overrides["efSearch"] = float(self._coerce_positive_int(ef_search, "ef_search"))
        if quantizer_ef_search is not None:
            overrides["quantizer_efSearch"] = float(
                self._coerce_positive_int(quantizer_ef_search, "quantizer_ef_search")
            )
        if k_factor is not None:
            overrides["k_factor"] = self._coerce_positive_float(k_factor, "k_factor", minimum=1.0)
        return overrides

    def _apply_runtime_overrides(
        self,
        overrides: Mapping[str, float],
        *,
        parameter_space: str | None = None,
        persist: bool = True,
    ) -> None:
        """Apply runtime parameter overrides to index and manager state.

        Parameters
        ----------
        overrides : Mapping[str, float]
            Dictionary of parameter overrides to apply.
        parameter_space : str | None, optional
            Parameter space description string to store.
        persist : bool, optional
            Whether to persist changes to metadata snapshot. Defaults to True.
        """
        if not overrides:
            return
        for key, value in overrides.items():
            self._runtime_overrides[key] = float(value)
            if key == "k_factor":
                self.refine_k_factor = float(value)
        if self.cpu_index is not None:
            self.apply_runtime_parameters(self._runtime_overrides)
        if parameter_space:
            self._parameter_space = parameter_space
        if persist:
            self._write_meta_snapshot(parameter_space=self._parameter_space)

    def _reset_runtime_overrides(self) -> None:
        """Reset runtime overrides to defaults and update index parameters."""
        self._runtime_overrides.clear()
        self.refine_k_factor = self._default_refine_k_factor
        if self.cpu_index is not None:
            self.apply_runtime_parameters(self._runtime_overrides)
        self._parameter_space = None
        self._write_meta_snapshot()

    def _parse_parameter_string(self, param_str: str) -> tuple[dict[str, float], str]:
        """Parse parameter string into overrides dictionary and normalized string.

        Parameters
        ----------
        param_str : str
            Parameter string in format "key=value,key2=value2".

        Returns
        -------
        tuple[dict[str, float], str]
            Tuple of (overrides dictionary, normalized parameter string).

        Raises
        ------
        ValueError
            If parameter string is empty, invalid format, or contains unsupported keys.
        """
        if not param_str or not param_str.strip():
            msg = "Parameter string cannot be empty"
            raise ValueError(msg)
        overrides: dict[str, float] = {}
        segments = [segment.strip() for segment in param_str.split(",") if segment.strip()]
        if not segments:
            msg = "Parameter string did not contain assignments"
            raise ValueError(msg)
        for segment in segments:
            if "=" not in segment:
                msg = f"Unsupported parameter fragment: {segment}"
                raise ValueError(msg)
            key, raw_value = (part.strip() for part in segment.split("=", 1))
            normalized_key = self._PARAMETER_ALIASES.get(key)
            if normalized_key is None:
                msg = f"Unsupported parameter: {key}"
                raise ValueError(msg)
            if normalized_key == "k_factor":
                overrides[normalized_key] = self._coerce_positive_float(raw_value, key, minimum=1.0)
            else:
                overrides[normalized_key] = float(self._coerce_positive_int(raw_value, key))
        normalized = ",".join(
            f"{key}={value if key == 'k_factor' else int(value)}"
            for key, value in overrides.items()
        )
        return overrides, normalized

    @staticmethod
    def _coerce_positive_int(value: object, field: str) -> int:
        """Coerce value to positive integer.

        Parameters
        ----------
        value : object
            Value to coerce (int, float, or str).
        field : str
            Field name for error messages.

        Returns
        -------
        int
            Positive integer value.

        Raises
        ------
        TypeError
            If value type is invalid (bool or other non-numeric type).
        ValueError
            If value is not positive.
        """
        if isinstance(value, bool):
            msg = f"Invalid integer override for {field}"
            raise TypeError(msg)
        if isinstance(value, (int, float)):
            result = int(value)
        elif isinstance(value, str):
            result = int(value.strip())
        else:
            msg = f"Invalid integer override for {field}"
            raise TypeError(msg)
        if result <= 0:
            msg = f"{field} must be positive"
            raise ValueError(msg)
        return result

    @staticmethod
    def _coerce_positive_float(value: object, field: str, *, minimum: float = 0.0) -> float:
        """Coerce value to positive float with optional minimum.

        Parameters
        ----------
        value : object
            Value to coerce (int, float, or str).
        field : str
            Field name for error messages.
        minimum : float, optional
            Minimum allowed value. Defaults to 0.0.

        Returns
        -------
        float
            Float value >= minimum.

        Raises
        ------
        TypeError
            If value type is invalid (bool or other non-numeric type).
        ValueError
            If value is less than minimum.
        """
        if isinstance(value, bool):
            msg = f"Invalid float override for {field}"
            raise TypeError(msg)
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            result = float(value.strip())
        else:
            msg = f"Invalid float override for {field}"
            raise TypeError(msg)
        if result < minimum:
            msg = f"{field} must be >= {minimum}"
            raise ValueError(msg)
        return result


__all__ = ["FAISSManager", "FAISSRuntimeOptions", "RefineSearchConfig"]
