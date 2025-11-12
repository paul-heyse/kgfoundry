"""Typing façade for codeintel_rev heavy optional dependencies.

This module centralizes numpy-style array aliases and exposes a wrapper around
``kgfoundry_common.typing.gate_import`` that is aware of the local heavy
dependency policy. Keeping aliases and dependency metadata in one place lets
lint/type tooling (PR-E) and runtime helpers share the same source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from os import PathLike
from typing import TYPE_CHECKING, Any, Protocol

from kgfoundry_common.typing import HEAVY_DEPS as _BASE_HEAVY_DEPS
from kgfoundry_common.typing import gate_import as _base_gate_import

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    type NDArrayF32 = npt.NDArray[np.float32]
    type NDArrayI64 = npt.NDArray[np.int64]
    type NDArrayAny = npt.NDArray[Any]
else:  # pragma: no cover
    NDArrayF32 = Any
    NDArrayI64 = Any
    NDArrayAny = Any

__all__ = [
    "HEAVY_DEPS",
    "FaissModule",
    "NDArrayAny",
    "NDArrayF32",
    "NDArrayI64",
    "NumpyModule",
    "PolarsModule",
    "TorchModule",
    "gate_import",
]


HEAVY_DEPS = _BASE_HEAVY_DEPS
"""Re-exported heavy dependency registry (single source of truth)."""


def gate_import(
    module_name: str,
    purpose: str,
    *,
    min_version: str | None = None,
) -> object:
    """Resolve ``module_name`` lazily using the heavy dependency policy.

    Extended Summary
    ----------------
    This function provides lazy import resolution for heavy optional dependencies
    (e.g., numpy, fastapi, FAISS) using the shared gate helper. It validates
    module availability, checks minimum version requirements, and provides helpful
    error messages if dependencies are missing. Used throughout the codebase to
    safely import optional dependencies without breaking on minimal installations.

    Parameters
    ----------
    module_name : str
        Name of the module to import (e.g., "numpy", "faiss"). The module must
        be registered in the heavy dependency registry.
    purpose : str
        Human-readable purpose description for the import (e.g., "vector operations",
        "FAISS index management"). Used in error messages if the module is unavailable.
    min_version : str | None, optional
        Optional minimum version requirement (e.g., "1.24.0"). If provided, the
        module version is validated against this requirement.

    Returns
    -------
    object
        Imported module or attribute returned by the shared gate helper. The return
        type depends on the module structure.

    Notes
    -----
    This function delegates to the base gate helper from kgfoundry_common.typing.
    It provides a consistent API for lazy imports across the codebase. Time
    complexity: O(1) for cached imports, O(import_time) for first-time imports.
    """
    return _base_gate_import(module_name, purpose, min_version=min_version)


class TorchDeviceProperties(Protocol):
    """Subset of torch.cuda device properties accessed by diagnostics."""

    total_memory: int


class TorchCudaAPI(Protocol):
    """Minimal CUDA API surface used throughout the codebase."""

    def is_available(self) -> bool: ...

    def device_count(self) -> int: ...

    def current_device(self) -> int: ...

    def get_device_name(self, index: int) -> str: ...

    def get_device_capability(self, index: int) -> tuple[int, int]: ...

    def get_device_properties(self, index: int) -> TorchDeviceProperties: ...

    def synchronize(self) -> None: ...

    def init(self) -> None: ...


class TorchTensor(Protocol):
    """Tensor operations invoked inside diagnostics."""

    def __matmul__(self, other: TorchTensor) -> TorchTensor: ...

    @property
    # lint-ignore: N802 matches torch.Tensor API
    def T(self) -> TorchTensor: ...  # noqa: N802

    def sum(self) -> TorchTensor: ...

    def item(self) -> float: ...


class TorchModule(Protocol):
    """Subset of torch's module-level API we rely on."""

    cuda: TorchCudaAPI

    def device(self, name: str) -> object:
        """Create a device object from name string."""
        ...

    def randn(self, *shape: int, device: object | None = None) -> TorchTensor:
        """Generate random tensor with standard normal distribution."""
        ...

    def matmul(self, left: TorchTensor, right: TorchTensor) -> TorchTensor:
        """Matrix multiplication of two tensors."""
        ...


class FaissStandardGpuResources(Protocol):
    """GPU resource handle for FAISS."""


class FaissGpuClonerOptions(Protocol):
    """Options controlling FAISS GPU cloning behavior."""

    use_cuvs: bool

    def __init__(self) -> None: ...


class FaissIndex(Protocol):
    """Minimal FAISS index surface used in diagnostics."""

    ntotal: int


class FaissGpuIndexFlatIP(FaissIndex, Protocol):
    """GPU FAISS index used for smoke testing."""

    def add(self, vectors: NDArrayF32) -> None:
        """Add vectors to the index."""
        ...

    def search(self, queries: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
        """Search for k nearest neighbors."""
        ...


class FaissModule(Protocol):
    """Subset of the FAISS module accessed via gate_import."""

    class _ResourceCtor(Protocol):
        def __call__(self) -> FaissStandardGpuResources: ...

    class _IndexCtor(Protocol):
        def __call__(
            self, resources: FaissStandardGpuResources, dim: int
        ) -> FaissGpuIndexFlatIP: ...

    StandardGpuResources: _ResourceCtor
    GpuClonerOptions: type[FaissGpuClonerOptions]
    GpuIndexFlatIP: _IndexCtor
    GpuIndexCagra: object | None

    def get_num_gpus(self) -> int:
        """Return the number of available GPUs."""
        ...

    # lint-ignore: N802 FAISS API uses camelCase
    def normalize_L2(self, vectors: NDArrayF32) -> None:  # noqa: N802
        """Normalize vectors using L2 norm in-place."""
        ...

    def index_cpu_to_gpu(
        self,
        resources: FaissStandardGpuResources,
        device: int,
        index: FaissIndex,
        options: FaissGpuClonerOptions | None = None,
    ) -> FaissIndex:
        """Clone CPU index to GPU."""
        ...


class NumpyRandomState(Protocol):
    """Random state wrapper for numpy.random."""

    def randn(self, *shape: int) -> NDArrayF32: ...


class NumpyRandomNamespace(Protocol):
    """Namespace for numpy.random helpers."""

    # lint-ignore: N802 mirrors numpy API
    def RandomState(self, seed: int) -> NumpyRandomState: ...  # noqa: N802


class NumpyLinalgNamespace(Protocol):
    """Namespace for numpy.linalg helpers."""

    # lint-ignore: FBT001 signature mirrors numpy
    def norm(self, array: NDArrayF32, axis: int, keepdims: bool) -> NDArrayF32: ...  # noqa: FBT001


class NumpyModule(Protocol):
    """Enough of numpy's surface for lazy imports."""

    random: NumpyRandomNamespace
    linalg: NumpyLinalgNamespace


class PolarsDataFrame(Protocol):
    """Subset of polars.DataFrame used for Parquet exports."""

    def write_parquet(self, file: str | PathLike[str]) -> None: ...


class PolarsModule(Protocol):
    """Minimal polars API used within optional export helpers."""

    # lint-ignore: N802 preserves polars constructor name
    def DataFrame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame:  # noqa: N802
        """Create a DataFrame from a sequence of mappings.

        Parameters
        ----------
        data : Sequence[Mapping[str, object]]
            Sequence of dictionary-like objects to convert to a DataFrame.

        Returns
        -------
        PolarsDataFrame
            DataFrame instance containing the provided data.
        """
        ...
