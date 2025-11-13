"""Typing façade for codeintel_rev heavy optional dependencies.

This module centralizes numpy-style array aliases and exposes a wrapper around
``kgfoundry_common.typing.gate_import`` that is aware of the local heavy
dependency policy. Keeping aliases and dependency metadata in one place lets
lint/type tooling (PR-E) and runtime helpers share the same source of truth.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from os import PathLike
from typing import TYPE_CHECKING, Any, Literal, Protocol

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
    "PolarsDataFrame",
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

    def is_available(self) -> bool:
        """Check if CUDA is available on the system.

        Returns
        -------
        bool
            True if CUDA is available and can be used, False otherwise.
        """
        ...

    def device_count(self) -> int:
        """Get the number of available CUDA devices.

        Returns
        -------
        int
            Number of CUDA-capable GPUs available on the system.
        """
        ...

    def current_device(self) -> int:
        """Get the index of the currently selected CUDA device.

        Returns
        -------
        int
            Index of the currently active CUDA device (0-based).
        """
        ...

    def get_device_name(self, index: int) -> str:
        """Get the name of a CUDA device.

        Parameters
        ----------
        index : int
            Device index (0-based) to query.

        Returns
        -------
        str
            Human-readable device name (e.g., "NVIDIA GeForce RTX 3090").
        """
        ...

    def get_device_capability(self, index: int) -> tuple[int, int]:
        """Get the compute capability of a CUDA device.

        Parameters
        ----------
        index : int
            Device index (0-based) to query.

        Returns
        -------
        tuple[int, int]
            Tuple of (major, minor) compute capability version (e.g., (8, 6)
            for compute capability 8.6).
        """
        ...

    def get_device_properties(self, index: int) -> TorchDeviceProperties:
        """Get properties of a CUDA device.

        Parameters
        ----------
        index : int
            Device index (0-based) to query.

        Returns
        -------
        TorchDeviceProperties
            Device properties object containing memory information and other
            device characteristics.
        """
        ...

    def synchronize(self) -> None:
        """Synchronize all CUDA operations on the current device.

        Blocks until all CUDA operations on the current device have completed.
        Used to ensure operations are finished before proceeding.
        """
        ...

    def init(self) -> None:
        """Initialize CUDA runtime.

        Performs one-time initialization of the CUDA runtime. Safe to call
        multiple times (idempotent).
        """
        ...


class TorchTensor(Protocol):
    """Tensor operations invoked inside diagnostics."""

    def __matmul__(self, other: TorchTensor) -> TorchTensor:
        """Matrix multiplication operator.

        Parameters
        ----------
        other : TorchTensor
            Right-hand operand for matrix multiplication.

        Returns
        -------
        TorchTensor
            Result tensor from matrix multiplication.
        """
        ...

    @property
    def transpose(self) -> TorchTensor:
        """Transpose property mirroring ``torch.Tensor.T``."""
        ...

    def __getattr__(self, name: Literal["T"]) -> TorchTensor:
        """Return torch-style transpose alias."""
        ...

    def sum(self) -> TorchTensor:
        """Sum all elements of the tensor.

        Returns
        -------
        TorchTensor
            Scalar tensor containing the sum of all elements.
        """
        ...

    def item(self) -> float:
        """Extract scalar value from single-element tensor.

        Returns
        -------
        float
            Python scalar value extracted from the tensor. Raises ValueError
            if the tensor contains more than one element.
        """
        ...


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

    def normalize_l2(self, vectors: NDArrayF32) -> None:
        """Normalize vectors using L2 norm in-place."""
        ...

    def __getattr__(self, name: Literal["normalize_L2"]) -> Callable[[NDArrayF32], None]:
        """Provide FAISS-compatible alias for ``normalize_L2``."""
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

    def randn(self, *shape: int) -> NDArrayF32:
        """Generate random array from standard normal distribution.

        Parameters
        ----------
        *shape : int
            Variable-length shape arguments defining the output array dimensions
            (e.g., randn(3, 4) creates a 3x4 array).

        Returns
        -------
        NDArrayF32
            Random array with specified shape, sampled from standard normal
            distribution (mean=0, std=1), dtype float32.
        """
        ...


class NumpyRandomNamespace(Protocol):
    """Namespace for numpy.random helpers."""

    def random_state(self, seed: int) -> NumpyRandomState:
        """Create a random state generator with fixed seed.

        Parameters
        ----------
        seed : int
            Random seed value for reproducible random number generation.

        Returns
        -------
        NumpyRandomState
            Random state instance initialized with the given seed, providing
            methods for generating random arrays with reproducible sequences.
        """
        ...

    def __getattr__(self, name: Literal["RandomState"]) -> Callable[[int], NumpyRandomState]:
        """Expose numpy-style ``RandomState`` constructor."""
        ...


class NumpyLinalgNamespace(Protocol):
    """Namespace for numpy.linalg helpers."""

    def norm(self, array: NDArrayF32, axis: int, *, keepdims: bool) -> NDArrayF32:
        """Compute vector or matrix norm along specified axis.

        Parameters
        ----------
        array : NDArrayF32
            Input array to compute norm for, dtype float32.
        axis : int
            Axis along which to compute the norm. If negative, counts from the last axis.
        keepdims : bool
            If True, keep reduced dimensions with size 1 in the result. If False,
            remove reduced dimensions.

        Returns
        -------
        NDArrayF32
            Norm values computed along the specified axis, dtype float32. Shape
            depends on input shape and keepdims parameter.
        """
        ...


class NumpyModule(Protocol):
    """Enough of numpy's surface for lazy imports."""

    random: NumpyRandomNamespace
    linalg: NumpyLinalgNamespace


class PolarsDataFrame(Protocol):
    """Subset of polars.DataFrame used for Parquet exports."""

    def write_parquet(self, file: str | PathLike[str]) -> None:
        """Write DataFrame to Parquet format.

        Parameters
        ----------
        file : str | PathLike[str]
            File system path (string or path-like object) where the Parquet file
            will be written. The file will be created or overwritten.

        Notes
        -----
        This method writes the DataFrame contents to a Parquet file using efficient
        columnar storage format. The method may raise IOError if the file cannot
        be written (e.g., permission denied, disk full).
        """
        ...


class PolarsModule(Protocol):
    """Minimal polars API used within optional export helpers."""

    DataFrame: Callable[[Sequence[Mapping[str, object]]], PolarsDataFrame]
    """Primary DataFrame constructor exposed by modern polars versions."""

    def data_frame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame:
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

    def __getattr__(
        self, name: Literal["DataFrame"]
    ) -> Callable[[Sequence[Mapping[str, object]]], PolarsDataFrame]:
        """Expose polars ``DataFrame`` constructor alias."""
        ...
