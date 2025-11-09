"""GPU-aware FAISS index helpers backed by the shared search API facade."""

# [nav:section public-api]

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from weakref import WeakKeyDictionary

import numpy as np

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.numpy_typing import normalize_l2
from search_api.faiss_gpu import (
    clone_index_to_gpu,
    configure_search_parameters,
    detect_gpu_context,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    import numpy.typing as npt

    from kgfoundry_common.numpy_typing import FloatMatrix, FloatVector, IntVector
    from search_api.faiss_gpu import (
        GpuContext,
    )
    from search_api.types import FaissIndexProtocol, FaissModuleProtocol

    type FloatArray = npt.NDArray[np.float32]
    type IntArray = npt.NDArray[np.int64]
    type StrArray = npt.NDArray[np.str_]
    type VecArray = npt.NDArray[np.float32]
else:  # pragma: no cover - runtime fallback
    FloatArray = np.ndarray
    IntArray = np.ndarray
    StrArray = np.ndarray
    VecArray = np.ndarray

__all__ = [
    "FaissGpuIndex",
    "FloatArray",
    "IntArray",
    "StrArray",
    "VecArray",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _FaissGpuIndexState:
    """Cache entry for prepared GPU indices."""

    context: GpuContext | None = None
    index: FaissIndexProtocol | None = None


_FAISS_GPU_CACHE: WeakKeyDictionary[FaissGpuIndex, _FaissGpuIndexState]


_FAISS_GPU_CACHE = WeakKeyDictionary()


def _get_gpu_state(index: FaissGpuIndex) -> _FaissGpuIndexState:
    return _FAISS_GPU_CACHE.get(index, _FaissGpuIndexState())


def _set_gpu_state(
    index: FaissGpuIndex,
    *,
    context: GpuContext | None,
    prepared: FaissIndexProtocol | None,
) -> None:
    _FAISS_GPU_CACHE[index] = _FaissGpuIndexState(context=context, index=prepared)


@dataclass(slots=True, frozen=True)
# [nav:anchor FaissGpuIndex]
class FaissGpuIndex:
    """Small GPU-aware facade that delegates to :mod:`search_api.faiss_gpu`.

    The facade keeps GPU initialisation idempotent by caching the detected context. If GPUs or cuVS
    helpers are unavailable, the CPU index is returned unchanged, ensuring safe fallbacks without
    caller intervention.
    """

    faiss_module: FaissModuleProtocol
    factory: str
    metric: str
    nprobe: int = 64
    use_gpu: bool = True
    use_cuvs: bool = True
    devices: Sequence[int] = (0,)

    def prepare(self, trained_index: FaissIndexProtocol) -> FaissIndexProtocol:
        """Clone ``trained_index`` to GPU when possible and set search parameters.

        The method is safe to call repeatedly; once a GPU index has been prepared it is reused on
        subsequent invocations. Any failures during cloning or configuration are logged and the CPU
        index is returned.

        Parameters
        ----------
        trained_index : FaissIndexProtocol
            Trained CPU index to prepare.

        Returns
        -------
        FaissIndexProtocol
            GPU index if available, otherwise CPU index.
        """
        if not self.use_gpu:
            logger.debug("GPU acceleration disabled; using CPU index only")
            _set_gpu_state(self, context=None, prepared=trained_index)
            return trained_index

        context = detect_gpu_context(
            self.faiss_module,
            use_cuvs=self.use_cuvs,
            device_ids=self.devices,
        )
        if context is None:
            logger.debug("GPU helpers missing; falling back to CPU index")
            _set_gpu_state(self, context=None, prepared=trained_index)
            return trained_index

        gpu_index = clone_index_to_gpu(trained_index, context)
        configure_search_parameters(
            self.faiss_module, gpu_index, nprobe=self.nprobe, gpu_enabled=True
        )
        _set_gpu_state(self, context=context, prepared=gpu_index)
        return gpu_index

    def search(self, query: FloatVector, k: int) -> list[tuple[int, float]]:
        """Execute a search against the prepared index returning ``(id, score)`` pairs.

        Parameters
        ----------
        query : FloatVector
            Query vector to search with.
        k : int
            Number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            List of (id, score) pairs.

        Raises
        ------
        RuntimeError
            If index has not been prepared.
        """
        state = _get_gpu_state(self)
        if state.index is None:
            msg = "FAISS GPU index not prepared"
            raise RuntimeError(msg)

        query_vector = np.asarray(query, dtype=np.float32).reshape(1, -1)
        normalized = normalize_l2(query_vector, axis=1)
        score_matrix, index_matrix = state.index.search(normalized, k)
        score_matrix_typed: FloatMatrix = np.asarray(score_matrix, dtype=np.float32)
        index_matrix_typed: IntVector = np.asarray(index_matrix, dtype=np.int64)
        score_vector: FloatVector = score_matrix_typed[0]
        index_vector: IntVector = index_matrix_typed[0]
        top_scores = cast("list[float]", score_vector.astype(np.float32, copy=False).tolist())
        top_indices = cast("list[int]", index_vector.astype(np.int64, copy=False).tolist())
        return list(zip(top_indices, top_scores, strict=False))
