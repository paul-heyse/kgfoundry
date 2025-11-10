"""FAISS dual-index utilities and metadata helpers."""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import numpy as np

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    import faiss

    from codeintel_rev.config.settings import IndexConfig

LOGGER = get_logger(__name__)

__all__ = ["FAISSDualIndexManager", "IndexManifest"]


@dataclass(slots=True, frozen=True)
class IndexManifest:
    """Persisted metadata for FAISS dual-index deployments."""

    version: str
    vec_dim: int
    index_type: str
    metric: str
    trained_on: str
    built_at: str
    gpu_enabled: bool
    primary_count: int
    secondary_count: int
    nlist: int | None = None
    pq_m: int | None = None
    cuvs_version: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> IndexManifest:
        """Load manifest metadata from a JSON document.

        Parameters
        ----------
        path : Path
            Filesystem path to the manifest JSON file.

        Returns
        -------
        IndexManifest
            Parsed manifest instance populated with the JSON payload.

        Raises
        ------
        TypeError
            If the JSON payload is not a mapping object.
        ValueError
            If required fields are missing or have incompatible types.
        """
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            msg = "Manifest JSON must be an object"
            raise TypeError(msg)

        try:
            return cls(**payload)
        except TypeError as exc:
            msg = f"Manifest file has unexpected structure: {exc}"
            raise ValueError(msg) from exc

    def to_file(self, path: Path) -> None:
        """Serialize the manifest to ``path`` as formatted JSON."""
        with path.open("w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, indent=2, sort_keys=True)
            handle.write("\n")


class FAISSDualIndexManager:
    """Manage dual FAISS indexes with CPU/GPU coordination."""

    def __init__(self, index_dir: Path, settings: IndexConfig, vec_dim: int) -> None:
        self._index_dir = index_dir
        self._settings = settings
        self._vec_dim = vec_dim

        self._primary_cpu: faiss.Index | None = None
        self._primary_gpu: faiss.Index | None = None
        self._secondary_cpu: faiss.Index | None = None
        self._secondary_gpu: faiss.Index | None = None
        self._manifest: IndexManifest | None = None
        self._faiss_module: ModuleType | None = None

        self._gpu_resources: faiss.StandardGpuResources | None = None
        self._gpu_enabled: bool = False
        self._gpu_disabled_reason: str | None = None

    def set_test_indexes(self, primary: faiss.Index | None, secondary: faiss.Index | None) -> None:
        """Set CPU indexes for testing purposes.

        This method allows tests to inject CPU indexes directly, bypassing
        the normal loading mechanism. It is public for testing purposes only.

        Parameters
        ----------
        primary : faiss.Index | None
            Primary CPU index to set.
        secondary : faiss.Index | None
            Secondary CPU index to set.
        """
        self._primary_cpu = primary
        self._secondary_cpu = secondary

    @property
    def gpu_enabled(self) -> bool:
        """Return ``True`` when GPU acceleration is enabled."""
        return self._gpu_enabled

    @property
    def gpu_disabled_reason(self) -> str | None:
        """Explain why GPU acceleration is disabled, if applicable."""
        return self._gpu_disabled_reason

    @property
    def primary_index(self) -> faiss.Index | None:
        """Return the loaded primary FAISS index, if available."""
        return self._primary_cpu

    @property
    def secondary_index(self) -> faiss.Index | None:
        """Return the loaded secondary FAISS index, if available."""
        return self._secondary_cpu

    @property
    def manifest(self) -> IndexManifest | None:
        """Return the cached index manifest metadata, if one was loaded."""
        return self._manifest

    async def ensure_ready(self) -> tuple[bool, str | None]:
        """Load FAISS artifacts from disk and prepare GPU state.

        Returns
        -------
        tuple[bool, str | None]
            ``(ready, reason)`` where ``ready`` indicates whether CPU indexes are
            available. ``reason`` carries a degradation message when GPU cloning
            fails or prerequisites are missing.
        """
        faiss_module, reason = self._import_faiss()
        if faiss_module is None:
            self._primary_cpu = None
            self._secondary_cpu = None
            return False, reason

        self._faiss_module = faiss_module

        primary_cpu, reason = await self._load_primary_index(faiss_module)
        if primary_cpu is None:
            self._primary_cpu = None
            self._secondary_cpu = None
            return False, reason
        self._primary_cpu = primary_cpu

        self._secondary_cpu = await self._load_secondary_index(faiss_module)
        self._load_manifest()
        self._reset_gpu_state()
        await self.try_gpu_clone(faiss_module)

        LOGGER.info(
            "faiss_ready",
            extra={
                "primary_count": int(getattr(self._primary_cpu, "ntotal", 0)),
                "secondary_count": int(getattr(self._secondary_cpu, "ntotal", 0)),
                "gpu_enabled": self._gpu_enabled,
                "gpu_reason": self._gpu_disabled_reason,
                "index_dir": str(self._index_dir),
            },
        )

        return True, self._gpu_disabled_reason

    def close(self) -> None:
        """Release FAISS handles and GPU resources."""
        self._primary_cpu = None
        self._secondary_cpu = None
        self._primary_gpu = None
        self._secondary_gpu = None
        self._gpu_resources = None
        self._gpu_enabled = False
        self._gpu_disabled_reason = None
        LOGGER.debug("faiss_dual_index_closed", extra={"index_dir": str(self._index_dir)})

    def search(
        self,
        query_vec: np.ndarray,
        *,
        k: int = 10,
        nprobe: int | None = None,
    ) -> list[tuple[int, float]]:
        """Search primary and secondary indexes and merge results.

        Parameters
        ----------
        query_vec : np.ndarray
            Query vector with shape ``(vec_dim,)`` or ``(1, vec_dim)``.
        k : int, optional
            Number of results to return. Defaults to ``10``.
        nprobe : int | None, optional
            IVF probe count for the primary index. When ``None`` uses the
            configured ``IndexConfig.faiss_nprobe`` value.

        Returns
        -------
        list[tuple[int, float]]
            Top-``k`` ``(chunk_id, score)`` pairs sorted by decreasing score.

        Raises
        ------
        RuntimeError
            If the primary index has not been loaded via :meth:`ensure_ready`.
        ValueError
            If the query contains multiple vectors. Batch search support will be
            added in a future task.
        """
        if self._primary_cpu is None:
            msg = "Primary index has not been loaded. Call ensure_ready() first."
            raise RuntimeError(msg)

        primary_index = self._select_primary_index()
        secondary_index = self._select_secondary_index()
        nprobe_effective = nprobe if nprobe is not None else int(self._settings.faiss_nprobe)

        query = np.asarray(query_vec, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)
        elif query.shape[0] != 1:
            msg = "Only single-query searches are supported"
            raise ValueError(msg)

        faiss_module = self._faiss_module or importlib.import_module("faiss")
        query_norm = query.copy()
        faiss_module.normalize_L2(query_norm)

        fetch = max(k * 2, k)

        if hasattr(primary_index, "nprobe"):
            primary_index.nprobe = nprobe_effective
        distances_p, ids_p = primary_index.search(query_norm, fetch)

        if secondary_index is not None and getattr(secondary_index, "ntotal", 0) > 0:
            distances_s, ids_s = secondary_index.search(query_norm, fetch)
        else:
            distances_s = np.empty((1, 0), dtype=np.float32)
            ids_s = np.empty((1, 0), dtype=np.int64)

        results: dict[int, float] = {}
        for idx, score in zip(ids_p[0], distances_p[0], strict=True):
            if idx == -1:
                continue
            results[int(idx)] = max(results.get(int(idx), float("-inf")), float(score))

        for idx, score in zip(ids_s[0], distances_s[0], strict=True):
            if idx == -1:
                continue
            results[int(idx)] = max(results.get(int(idx), float("-inf")), float(score))

        sorted_results = sorted(results.items(), key=lambda item: item[1], reverse=True)
        return sorted_results[:k]

    async def add_incremental(self, vectors: np.ndarray, chunk_ids: np.ndarray) -> None:
        """Append vectors to the secondary index and persist them to disk.

        Parameters
        ----------
        vectors : np.ndarray
            2-D array of shape ``(n, vec_dim)`` containing the vectors to add. The
            vectors are L2-normalized before insertion.
        chunk_ids : np.ndarray
            1-D array of shape ``(n,)`` containing the chunk identifiers to bind to
            the provided vectors. IDs are coerced to ``int64``.

        Raises
        ------
        RuntimeError
            If :meth:`ensure_ready` has not been called yet.
        ValueError
            If the vectors do not match the configured embedding dimension or if
            the number of vectors differs from the number of chunk IDs.
        """
        if self._primary_cpu is None or self._secondary_cpu is None:
            msg = "FAISS indexes not loaded. Call ensure_ready() before add_incremental()."
            raise RuntimeError(msg)

        expected_rank = 2
        if vectors.ndim != expected_rank:
            msg = "vectors must have shape (n, vec_dim)"
            raise ValueError(msg)
        if vectors.shape[1] != self._vec_dim:
            msg = f"Vector dimension {vectors.shape[1]} does not match expected {self._vec_dim}"
            raise ValueError(msg)

        ids = np.asarray(chunk_ids, dtype=np.int64)
        if ids.ndim != 1:
            msg = "chunk_ids must be a 1-D array"
            raise ValueError(msg)
        if vectors.shape[0] != ids.shape[0]:
            msg = "vectors and chunk_ids must have the same length"
            raise ValueError(msg)
        if vectors.shape[0] == 0:
            return

        faiss_module = self._faiss_module or importlib.import_module("faiss")

        vectors32 = np.ascontiguousarray(vectors, dtype=np.float32)
        faiss_module.normalize_L2(vectors32)
        self._secondary_cpu.add_with_ids(vectors32, ids)

        secondary_path = self._index_dir / "secondary.faiss"
        await asyncio.to_thread(faiss_module.write_index, self._secondary_cpu, str(secondary_path))

        if self._gpu_enabled:
            if self._gpu_resources is None:
                self._gpu_enabled = False
                self._secondary_gpu = None
                self._primary_gpu = None
                self._gpu_disabled_reason = "GPU resources unavailable during incremental add"
                LOGGER.warning(
                    "faiss_gpu_incremental_disabled",
                    extra={"reason": self._gpu_disabled_reason},
                )
            else:
                try:
                    cloner_options = self._build_gpu_cloner_options(faiss_module)
                    self._secondary_gpu = self._clone_index_to_gpu(
                        faiss_module,
                        self._gpu_resources,
                        self._secondary_cpu,
                        cloner_options,
                    )
                except (AttributeError, RuntimeError) as exc:
                    self._secondary_gpu = None
                    self._primary_gpu = None
                    self._gpu_resources = None
                    self._gpu_enabled = False
                    self._gpu_disabled_reason = f"Secondary GPU clone failed: {exc}"
                    LOGGER.warning(
                        "faiss_gpu_incremental_clone_failed",
                        extra={"error": str(exc)},
                    )

        secondary_total = int(getattr(self._secondary_cpu, "ntotal", 0))
        LOGGER.info(
            "faiss_incremental_add",
            extra={
                "added": int(ids.size),
                "secondary_total": secondary_total,
                "index_dir": str(self._index_dir),
            },
        )

    def needs_compaction(self) -> bool:
        """Return ``True`` when the secondary index exceeds the compaction threshold.

        Returns
        -------
        bool
            ``True`` when ``secondary.ntotal / primary.ntotal`` is greater than the
            configured compaction threshold; otherwise ``False``.
        """
        if self._primary_cpu is None or self._secondary_cpu is None:
            return False

        primary_total = int(getattr(self._primary_cpu, "ntotal", 0))
        secondary_total = int(getattr(self._secondary_cpu, "ntotal", 0))
        if secondary_total == 0:
            return False

        threshold = float(getattr(self._settings, "compaction_threshold", 0.05))
        denominator = max(primary_total, 1)
        ratio = secondary_total / denominator
        return ratio > threshold

    def _reset_gpu_state(self) -> None:
        self._primary_gpu = None
        self._secondary_gpu = None
        self._gpu_resources = None
        self._gpu_enabled = False
        self._gpu_disabled_reason = None

    def _import_faiss(self) -> tuple[ModuleType | None, str | None]:
        try:
            return importlib.import_module("faiss"), None
        except ImportError as exc:  # pragma: no cover - executed when faiss missing
            reason = "FAISS library not installed"
            LOGGER.exception(
                "faiss_import_failed",
                extra={"error": str(exc), "index_dir": str(self._index_dir)},
            )
            return None, reason

    async def _load_primary_index(
        self, faiss_module: ModuleType
    ) -> tuple[faiss.Index | None, str | None]:
        primary_path = self._index_dir / "primary.faiss"
        if not primary_path.exists():
            reason = "Primary index not found"
            LOGGER.error(
                "faiss_primary_missing",
                extra={"path": str(primary_path)},
            )
            return None, reason

        try:
            primary_cpu = cast(
                "faiss.Index", await asyncio.to_thread(faiss_module.read_index, str(primary_path))
            )
        except RuntimeError as exc:
            reason = f"Failed to load primary index: {exc}"
            LOGGER.exception(
                "faiss_primary_load_failed",
                extra={"path": str(primary_path), "error": str(exc)},
            )
            return None, reason

        primary_dim = getattr(primary_cpu, "d", None)
        if primary_dim != self._vec_dim:
            reason = f"Dimension mismatch: index={primary_dim}, expected={self._vec_dim}"
            LOGGER.error(
                "faiss_dimension_mismatch",
                extra={
                    "path": str(primary_path),
                    "index_dim": primary_dim,
                    "expected_dim": self._vec_dim,
                },
            )
            return None, reason

        return primary_cpu, None

    async def _load_secondary_index(self, faiss_module: ModuleType) -> faiss.Index:
        secondary_path = self._index_dir / "secondary.faiss"
        if secondary_path.exists():
            try:
                return await asyncio.to_thread(faiss_module.read_index, str(secondary_path))
            except RuntimeError as exc:
                LOGGER.exception(
                    "faiss_secondary_load_failed",
                    extra={"path": str(secondary_path), "error": str(exc)},
                )

        return faiss_module.IndexFlatIP(self._vec_dim)

    def _load_manifest(self) -> None:
        manifest_path = self._index_dir / "primary.manifest.json"
        if not manifest_path.exists():
            self._manifest = None
            return

        try:
            self._manifest = IndexManifest.from_file(manifest_path)
        except (TypeError, ValueError) as exc:
            LOGGER.warning(
                "faiss_manifest_invalid",
                extra={"path": str(manifest_path), "error": str(exc)},
            )
            self._manifest = None

    async def try_gpu_clone(self, faiss_module: ModuleType) -> None:
        """Attempt to clone CPU indexes to GPU for acceleration.

        This method is public for testing purposes. It attempts to clone
        both primary and secondary CPU indexes to GPU if CUDA is available.

        Parameters
        ----------
        faiss_module : ModuleType
            FAISS module instance to use for GPU operations.
        """
        if self._primary_cpu is None or self._secondary_cpu is None:
            return

        try:
            torch = importlib.import_module("torch")
        except ImportError:  # pragma: no cover - torch optional
            self._gpu_disabled_reason = "PyTorch not installed"
            return

        try:
            if not torch.cuda.is_available():
                self._gpu_disabled_reason = "CUDA not available"
                return
        except RuntimeError as exc:  # pragma: no cover - defensive
            self._gpu_disabled_reason = f"CUDA check failed: {exc}"
            LOGGER.exception("faiss_cuda_check_failed", extra={"error": str(exc)})
            return

        try:
            gpu_resources = faiss_module.StandardGpuResources()
            cloner_options = self._build_gpu_cloner_options(faiss_module)

            primary_gpu = self._clone_index_to_gpu(
                faiss_module,
                gpu_resources,
                self._primary_cpu,
                cloner_options,
            )
            secondary_gpu = self._clone_index_to_gpu(
                faiss_module,
                gpu_resources,
                self._secondary_cpu,
                cloner_options,
            )
        except (AttributeError, RuntimeError) as exc:
            self._gpu_disabled_reason = f"GPU clone failed: {exc}"
            LOGGER.exception("faiss_gpu_clone_failed", extra={"error": str(exc)})
            return

        self._gpu_resources = gpu_resources
        self._primary_gpu = primary_gpu
        self._secondary_gpu = secondary_gpu
        self._gpu_enabled = True
        self._gpu_disabled_reason = None
        LOGGER.info(
            "faiss_gpu_clone_success",
            extra={"use_cuvs": bool(getattr(cloner_options, "use_cuvs", False))},
        )

    def _build_gpu_cloner_options(self, faiss_module: ModuleType) -> faiss.GpuClonerOptions:
        cloner_options = faiss_module.GpuClonerOptions()
        requested = bool(self._settings.use_cuvs)
        if hasattr(cloner_options, "use_cuvs"):
            try:
                cloner_options.use_cuvs = requested
            except AttributeError as exc:
                LOGGER.warning(
                    "faiss_gpu_cuvs_unavailable",
                    extra={"error": str(exc)},
                )
                cloner_options.use_cuvs = False
        elif requested:
            LOGGER.warning(
                "faiss_gpu_cuvs_unavailable",
                extra={"error": "GpuClonerOptions.use_cuvs missing"},
            )
        return cloner_options

    def _clone_index_to_gpu(
        self,
        faiss_module: ModuleType,
        gpu_resources: faiss.StandardGpuResources,
        cpu_index: faiss.Index,
        cloner_options: faiss.GpuClonerOptions,
    ) -> faiss.Index:
        try:
            return faiss_module.index_cpu_to_gpu(
                gpu_resources,
                0,
                cpu_index,
                cloner_options,
            )
        except (AttributeError, RuntimeError) as exc:
            if bool(self._settings.use_cuvs) and hasattr(cloner_options, "use_cuvs"):
                try:
                    cloner_options.use_cuvs = False
                except AttributeError:
                    LOGGER.warning(
                        "faiss_gpu_clone_cuvs_reset_failed",
                        extra={"error": str(exc)},
                    )
                else:
                    LOGGER.warning(
                        "faiss_gpu_clone_cuvs_fallback",
                        extra={"error": str(exc)},
                    )
                    return faiss_module.index_cpu_to_gpu(
                        gpu_resources,
                        0,
                        cpu_index,
                        cloner_options,
                    )
            raise

    def _select_primary_index(self) -> faiss.Index:
        if self._primary_cpu is None:
            msg = "Primary index not loaded"
            raise RuntimeError(msg)
        if self._gpu_enabled and self._primary_gpu is not None:
            return self._primary_gpu
        return self._primary_cpu

    def _select_secondary_index(self) -> faiss.Index | None:
        if self._secondary_cpu is None:
            return None
        if self._gpu_enabled and self._secondary_gpu is not None:
            return self._secondary_gpu
        return self._secondary_cpu
