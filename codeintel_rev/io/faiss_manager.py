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
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, cast

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
    merge_indexes as builder_merge_indexes,
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
    get_compile_options as store_compile_options,
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
    np = cast("Any", LazyModule("numpy", "FAISS manager vector operations"))
    DuckDBCatalog = Any

RefineSearchConfig = _RefineSearchConfig

# Lazy FAISS module
_faiss = LazyModule("faiss", "FAISS manager operations")
faiss = cast("Any", _faiss)

_DEFAULT_SWEEP = ("nprobe=16", "nprobe=32", "nprobe=64", "nprobe=96", "nprobe=128")


class _RuntimeFacade:
    """Helper exposing runtime tuning operations via :class:`FAISSManager`."""

    def __init__(self, manager: FAISSManager) -> None:
        self._manager = manager

    def get_runtime_tuning(self) -> dict[str, object]:
        """Return active runtime parameters, overrides, and profile metadata."""
        profile = self._manager._load_profile_payload(self._manager._resolve_profile_to_read())
        snapshot = self._manager._current_runtime_parameters()
        payload: dict[str, object] = {
            "active": snapshot,
            "overrides": dict(self._manager._runtime_overrides),
        }
        if profile is not None:
            payload["autotune_profile"] = profile
        if self._manager._parameter_space is not None:
            payload["parameter_space"] = self._manager._parameter_space
        return payload

    def apply_runtime_tuning(
        self,
        *,
        nprobe: int | None = None,
        ef_search: int | None = None,
        quantizer_ef_search: int | None = None,
        k_factor: float | None = None,
    ) -> dict[str, object]:
        """Apply runtime overrides to the active FAISS index."""
        overrides = self._manager._normalize_runtime_payload(
            nprobe=nprobe,
            ef_search=ef_search,
            quantizer_ef_search=quantizer_ef_search,
            k_factor=k_factor,
        )
        if not overrides:
            msg = "No overrides provided"
            raise ValueError(msg)
        self._manager._apply_runtime_overrides(overrides)
        return self.get_runtime_tuning()

    def reset_runtime_tuning(self) -> dict[str, object]:
        """Clear runtime overrides and revert to defaults."""
        self._manager._reset_runtime_overrides()
        return self.get_runtime_tuning()

    def set_search_parameters(self, param_str: str) -> dict[str, object]:
        """Apply FAISS ParameterSpace string (``nprobe=32,efSearch=64``)."""
        overrides, normalized = self._manager._parse_parameter_string(param_str)
        self._manager._apply_runtime_overrides(overrides, parameter_space=normalized)
        return self.get_runtime_tuning()


class FAISSManager:
    """FAISS index manager with adaptive indexing and incremental updates."""

    _PARAMETER_ALIASES = {
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

        # Live indexes
        self.cpu_index: FaissIndex | None = None
        self.secondary_index: FaissIndex | None = None
        self.incremental_ids: set[int] = set()

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
        self._runtime_facade = _RuntimeFacade(self)

    def build_index(self, vectors: NDArrayF32, *, family: str | None = None) -> None:
        """Build and train FAISS index with adaptive type selection."""
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
        self._faiss_factory = factory
        self._vector_count = int(vectors.shape[0])
        self._write_meta_snapshot(vector_count=self._vector_count, factory=factory)

    def add_vectors(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """Add vectors to the primary index after build."""
        if self.cpu_index is None:
            msg = "Primary index not initialized; call build_index() first."
            raise RuntimeError(msg)
        builder_add_vectors(self.cpu_index, vectors, ids)

    def update_index(self, new_vectors: NDArrayF32, new_ids: NDArrayI64) -> int:
        """Add vectors to the secondary (incremental) index."""
        if self.cpu_index is None:
            msg = "Primary index not initialized. Run build_index() or load_cpu_index() first."
            raise RuntimeError(msg)

        self._ensure_secondary()

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
        """Persist the primary CPU index to disk."""
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
        if export_idmap is not None:
            self.export_idmap(export_idmap)
        self._sync_runtime_from_meta()
        profile = self._load_profile_payload(profile_path or self._resolve_profile_to_read())
        if profile is not None:
            self._apply_profile_payload(profile)
        elif self._runtime_overrides:
            self._apply_runtime_overrides(self._runtime_overrides, persist=False)

    def save_secondary_index(self) -> None:
        """Persist the secondary index to disk (.secondary suffix)."""
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
        """Export {faiss_row -> external_id} mapping to Parquet."""
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return export_idmap_parquet(self.cpu_index, out_path)

    def get_idmap_array(self) -> NDArrayI64:
        """Get the ID map array from the primary index."""
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
        catalog: DuckDBCatalog | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Execute dual-index search with optional exact rerank."""
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)

        eff_k = int(k or self.default_k)
        eff_nprobe = int(nprobe or self.default_nprobe)

        k_factor = self.refine_k_factor
        if runtime is not None and runtime.k_factor is not None:
            k_factor = runtime.k_factor

        return runtime_search_dual(
            primary=self.cpu_index,
            secondary=self.secondary_index,
            query=query,
            k=eff_k,
            nprobe=eff_nprobe,
            refine_k_factor=k_factor,
            catalog=catalog,
        )

    def search_with_refine(
        self,
        query: NDArrayF32,
        *,
        k: int,
        catalog: DuckDBCatalog,
        config: RefineSearchConfig | None = None,
    ) -> list[SearchHit]:
        """Execute ANN search and return structured :class:`SearchHit` rows."""
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
        apply_runtime_parameters(
            self.cpu_index,
            nprobe=int(overrides.get("nprobe")) if overrides.get("nprobe") is not None else None,
            ef_search=int(overrides.get("efSearch")) if overrides.get("efSearch") is not None else None,
            quantizer_ef_search=(
                int(overrides.get("quantizer_efSearch"))
                if overrides.get("quantizer_efSearch") is not None
                else None
            ),
        )

    def merge_indexes(self) -> None:
        """Merge secondary index into primary and rebuild."""
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        if self.secondary_index is None:
            return

        self.cpu_index = builder_merge_indexes(self.cpu_index, self.secondary_index, self.vec_dim)
        self.secondary_index = None
        self.incremental_ids.clear()

    def require_cpu_index(self) -> FaissIndex:
        """Get the primary CPU index or raise if not initialized."""
        if self.cpu_index is None:
            msg = "Primary index not initialized."
            raise RuntimeError(msg)
        return self.cpu_index

    def active_index(self) -> FaissIndex:
        """Get the currently active index (primary or secondary)."""
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
        """Sweep ParameterSpace strings and persist the best profile."""
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
                overrides, normalized = self._parse_parameter_string(param_str)
                profile = {
                    "param_str": normalized,
                    "recall_at_k": recall,
                    "latency_ms": latency_ms,
                    "k": k,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "refine_k_factor": self.refine_k_factor,
                }
                profile.update({key: value for key, value in overrides.items()})
                best_profile = profile
                best_recall = recall
                best_latency = latency_ms

        if best_profile is None:
            msg = "Unable to evaluate sweep"
            raise RuntimeError(msg)

        save_tuning_profile(best_profile, self.autotune_profile_path)
        self._apply_profile_payload(best_profile)
        return best_profile

    def reconstruct_batch(self, ids: Sequence[int]) -> NDArrayF32:
        """Reconstruct vectors for a batch of chunk IDs."""
        return store_reconstruct_batch(self.require_cpu_index(), self.vec_dim, ids)

    def estimate_memory_usage(self, n_vectors: int) -> dict[str, int]:
        """Estimate memory usage in bytes for a given number of vectors."""
        if n_vectors <= 0:
            return {"cpu_index_bytes": 0, "total_bytes": 0}
        cfg = IndexBuildConfig(
            vec_dim=self.vec_dim,
            default_nlist=self.nlist,
            family=cast("IndexFamily", self.runtime_opts.faiss_family or "adaptive"),
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
            alt = n_vectors // 39 if n_vectors >= 39 else sqrt_n
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

    def get_compile_options(self) -> str:
        """Return FAISS compile options string when available."""
        return store_compile_options()

    def _write_meta_snapshot(
        self,
        *,
        vector_count: int | None = None,
        factory: str | None = None,
        parameter_space: str | None = None,
    ) -> None:
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

    def _resolve_profile_to_read(self) -> Path | None:
        for path in (self.autotune_profile_path, self._legacy_autotune_profile_path):
            if path and Path(path).exists():
                return Path(path)
        return None

    def _load_profile_payload(self, path: Path | None) -> dict[str, object] | None:
        if path is None:
            return None
        return load_tuned_profile(Path(path))

    def _apply_profile_payload(
        self,
        payload: Mapping[str, object],
        *,
        persist: bool = True,
    ) -> None:
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

    def _current_runtime_parameters(self) -> dict[str, object]:
        return {
            "nprobe": self._runtime_overrides.get("nprobe", self.default_nprobe),
            "efSearch": self._runtime_overrides.get("efSearch", self.hnsw_ef_search),
            "quantizer_efSearch": self._runtime_overrides.get("quantizer_efSearch"),
            "k_factor": self._runtime_overrides.get("k_factor", self.refine_k_factor),
        }

    def _normalize_runtime_payload(
        self,
        *,
        nprobe: object | None = None,
        ef_search: object | None = None,
        quantizer_ef_search: object | None = None,
        k_factor: object | None = None,
    ) -> dict[str, float]:
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
        self._runtime_overrides.clear()
        self.refine_k_factor = self._default_refine_k_factor
        if self.cpu_index is not None:
            self.apply_runtime_parameters(self._runtime_overrides)
        self._parameter_space = None
        self._write_meta_snapshot()

    def _parse_parameter_string(self, param_str: str) -> tuple[dict[str, float], str]:
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

    def _coerce_positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            msg = f"Invalid integer override for {field}"
            raise ValueError(msg)
        if isinstance(value, (int, float)):
            result = int(value)
        elif isinstance(value, str):
            result = int(value.strip())
        else:
            msg = f"Invalid integer override for {field}"
            raise ValueError(msg)
        if result <= 0:
            msg = f"{field} must be positive"
            raise ValueError(msg)
        return result

    def _coerce_positive_float(self, value: object, field: str, *, minimum: float = 0.0) -> float:
        if isinstance(value, bool):
            msg = f"Invalid float override for {field}"
            raise ValueError(msg)
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            result = float(value.strip())
        else:
            msg = f"Invalid float override for {field}"
            raise ValueError(msg)
        if result < minimum:
            msg = f"{field} must be >= {minimum}"
            raise ValueError(msg)
        return result


__all__ = ["FAISSManager", "FAISSRuntimeOptions", "RefineSearchConfig"]
