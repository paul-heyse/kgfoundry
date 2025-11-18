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

from kgfoundry_common.typing import EXTRAS_HINT
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
    "FaissIndex",
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
    import_func: Callable[[str], object] | None = None,
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
    import_func : Callable[[str], object] | None, optional
        Optional import callable to use for resolving modules. Primarily for
        tests to inject fake import behavior. Defaults to the shared gate helper.

    Returns
    -------
    object
        Imported module or attribute returned by the shared gate helper. The return
        type depends on the module structure.

    Raises
    ------
    ImportError
        If the module cannot be imported or fails minimum version checks. The error
        message includes installation guidance referencing the configured extras.

    Notes
    -----
    This function delegates to the base gate helper from kgfoundry_common.typing.
    It provides a consistent API for lazy imports across the codebase. Time
    complexity: O(1) for cached imports, O(import_time) for first-time imports.
    """
    if import_func is not None:
        try:
            return import_func(module_name)
        except ImportError as exc:
            module_root = module_name.split(".", maxsplit=1)[0]
            hint = EXTRAS_HINT.get(module_root)
            msg = f"Cannot proceed with {purpose}: '{module_name}' is not installed."
            if hint:
                if " or " in hint:
                    options = " or ".join(
                        f"pip install codeintel-rev[{option.strip()}]"
                        for option in hint.split(" or ")
                    )
                    msg = f"{msg} Install with: {options}"
                else:
                    msg = f"{msg} Install with: pip install codeintel-rev[{hint}]"
            else:
                msg = f"{msg} Install via: pip install {module_root}"
            raise ImportError(msg) from exc
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


class FaissIndex(Protocol):
    """Subset of ``faiss.Index`` methods used across kgfoundry."""

    ntotal: int
    d: int
    nprobe: int
    is_trained: bool

    def add(self, vectors: NDArrayF32) -> None:
        """Add normalized vectors to the index.

        Extended Summary
        ----------------
        Appends a batch of normalized vectors to the FAISS index. Vectors must
        be L2-normalized (unit length) for inner product metrics or properly
        scaled for L2 distance metrics. This is the primary method for populating
        an index with vectors for subsequent similarity search operations.

        Parameters
        ----------
        vectors : NDArrayF32
            Array of shape (n_vectors, d) where n_vectors is the number of vectors
            to add and d matches the index dimension. Vectors must be normalized
            according to the index metric (L2-normalized for inner product).

        Notes
        -----
        The index must be trained (for IVF/PQ families) before adding vectors.
        Time complexity: O(n_vectors * d) for flat indexes, varies for approximate
        indexes. This operation modifies the index in-place and increments ntotal.
        """
        ...

    def add_with_ids(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """Add vectors with explicit identifiers.

        Extended Summary
        ----------------
        Appends vectors to the index with user-specified integer identifiers.
        Used when you need to maintain a mapping between vectors and external
        identifiers (e.g., document IDs, row indices). The IDs must be unique
        and non-negative.

        Parameters
        ----------
        vectors : NDArrayF32
            Array of shape (n_vectors, d) containing normalized vectors to add.
        ids : NDArrayI64
            Array of shape (n_vectors,) containing integer identifiers for each
            vector. Must be unique and non-negative. Length must match n_vectors.

        Notes
        -----
        This method is required when using IDMap wrappers or when you need to
        preserve external identifiers. Time complexity matches add() plus ID
        mapping overhead. IDs are stored internally and returned in search results.
        """
        ...

    def train(self, vectors: NDArrayF32) -> None:
        """Train the index when required (IVF/PQ families).

        Extended Summary
        ----------------
        Trains the index on a representative sample of vectors. Required for
        approximate indexes that use clustering (IVF) or quantization (PQ).
        Training learns the index structure (cluster centroids, codebooks) from
        the provided vectors. Must be called before add() for trainable indexes.

        Parameters
        ----------
        vectors : NDArrayF32
            Training vectors of shape (n_train, d) where n_train should be
            sufficient for the index type (typically >= nlist for IVF indexes).
            The d dimension must match the index dimension.

        Notes
        -----
        Training is a one-time operation that must complete before adding vectors.
        Time complexity: O(n_train * d * iterations) for clustering-based methods.
        After training, is_trained becomes True. Flat indexes (IndexFlat*) do not
        require training and this method is a no-op.
        """
        ...

    def search(self, vectors: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
        """Search the index for ``k`` nearest neighbors.

        Extended Summary
        ----------------
        Performs approximate nearest neighbor search for a batch of query vectors.
        Returns the k closest vectors in the index along with their distances and
        identifiers. This is the core retrieval operation used for similarity search
        and vector database queries.

        Parameters
        ----------
        vectors : NDArrayF32
            Query vectors of shape (n_queries, d) where n_queries is the number
            of queries and d matches the index dimension. Vectors should be
            normalized according to the index metric.
        k : int
            Number of nearest neighbors to retrieve per query. Must be positive
            and not exceed ntotal. Larger k values improve recall but increase
            computation time.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Tuple of (distances, indices) where:
            - distances: Array of shape (n_queries, k) containing similarity scores
              or distances (higher is better for inner product, lower is better
              for L2 distance).
            - indices: Array of shape (n_queries, k) containing the indices of
              the k nearest neighbors in the index (or external IDs if IDMap is used).

        Notes
        -----
        Search performance depends on index type and nprobe parameter (for IVF
        indexes). Time complexity: O(n_queries * k * d) for flat indexes,
        O(n_queries * nprobe * d) for IVF indexes. Results are sorted by distance
        (descending for inner product, ascending for L2).
        """
        ...

    def reconstruct(self, idx: int) -> NDArrayAny:
        """Reconstruct a vector stored in the index by identifier."""
        ...

    def make_direct_map(self) -> None:
        """Enable FAISS direct-map support when available.

        Extended Summary
        ----------------
        Enables direct access to stored vectors by their index positions. This
        allows reconstructing vectors from their compressed representations
        (e.g., PQ codes) without requiring a separate storage backend. Useful
        for applications that need to retrieve the original vectors after search.

        Notes
        -----
        Direct map support is only available for certain index types (e.g., IndexIVF
        with direct_map enabled). Enabling direct maps increases memory usage but
        enables fast vector reconstruction. This operation modifies the index
        structure and may require re-adding vectors depending on the index type.
        """
        ...


class FaissParameterSpace(Protocol):
    """Runtime tuning surface exposed by ``faiss.ParameterSpace``."""

    def initialize(self, index: FaissIndex) -> None:
        """Initialize the parameter space for the provided index.

        Extended Summary
        ----------------
        Prepares the parameter space object for runtime tuning of the given index.
        This must be called before set_index_parameters() to establish the mapping
        between parameter names and index internals. Used for optimizing search
        performance (e.g., adjusting nprobe for IVF indexes).

        Parameters
        ----------
        index : FaissIndex
            FAISS index instance to initialize parameter space for. The index
            must be trained and populated before parameter tuning.

        Notes
        -----
        Initialization analyzes the index structure to determine which parameters
        can be tuned at runtime. This is a lightweight operation that prepares
        the parameter space for subsequent tuning calls.
        """
        ...

    def set_index_parameters(self, index: FaissIndex, params: str) -> None:
        """Apply parameter overrides (``nprobe=64``) to ``index``.

        Extended Summary
        ----------------
        Dynamically adjusts runtime parameters of a FAISS index to optimize
        search performance. Common parameters include nprobe (number of clusters
        to search in IVF indexes) which trades off search speed vs. recall.
        Parameters are specified as a string in key=value format.

        Parameters
        ----------
        index : FaissIndex
            FAISS index instance to modify. Must have been initialized via
            initialize() before calling this method.
        params : str
            Parameter string in key=value format, e.g., "nprobe=64". Multiple
            parameters can be specified separated by commas. Valid parameters
            depend on the index type.

        Notes
        -----
        Parameter changes take effect immediately for subsequent search() calls.
        This allows runtime tuning without rebuilding the index. Common use case:
        increase nprobe for higher recall at the cost of slower search. Time
        complexity: O(1) for parameter updates, but affects subsequent search
        performance.
        """
        ...


class FaissModule(Protocol):
    """Subset of the FAISS module accessed via gate_import."""

    METRIC_INNER_PRODUCT: int
    METRIC_L2: int
    IndexFlatIP: Callable[[int], FaissIndex]
    IndexIDMap2: Callable[[FaissIndex], FaissIndex]
    IndexIVFFlat: Callable[[FaissIndex, int, int, int], FaissIndex]

    def normalize_l2(self, vectors: NDArrayF32) -> None:
        """Normalize vectors using L2 norm in-place.

        Extended Summary
        ----------------
        Normalizes vectors to unit length (L2 norm = 1) by dividing each vector
        by its Euclidean norm. This is required before adding vectors to indexes
        that use inner product metric, as inner product on normalized vectors
        is equivalent to cosine similarity.

        Parameters
        ----------
        vectors : NDArrayF32
            Array of shape (n_vectors, d) containing vectors to normalize.
            Modified in-place. Zero vectors remain unchanged (division by zero
            is avoided).

        Notes
        -----
        Normalization is performed in-place, modifying the input array. Time
        complexity: O(n_vectors * d). This operation is idempotent (normalizing
        already-normalized vectors has no effect). Required for IndexFlatIP and
        other inner product indexes.
        """
        ...

    def __getattr__(self, name: Literal["normalize_L2"]) -> Callable[[NDArrayF32], None]:
        """Provide FAISS-compatible alias for ``normalize_L2``."""
        ...

    def index_factory(self, dimension: int, factory: str, metric: int) -> FaissIndex:
        """Build an index via factory string.

        Extended Summary
        ----------------
        Creates a FAISS index from a factory string specification. Factory strings
        provide a concise way to specify index types and parameters (e.g.,
        "IVF1024,Flat" for IVF index with 1024 clusters). This is the preferred
        method for creating indexes as it's more flexible than individual constructors.

        Parameters
        ----------
        dimension : int
            Vector dimension (d). All vectors added to the index must have this
            dimension. Must be positive.
        factory : str
            Factory string specifying index type and parameters. Examples:
            "Flat" (exact search), "IVF1024,Flat" (IVF with 1024 clusters),
            "IVF1024,PQ64" (IVF with PQ quantization). See FAISS documentation
            for full syntax.
        metric : int
            Distance metric constant. Use METRIC_INNER_PRODUCT for cosine similarity
            (requires normalized vectors) or METRIC_L2 for Euclidean distance.

        Returns
        -------
        FaissIndex
            Newly created FAISS index instance matching the factory specification.
            The index is untrained and empty (ntotal=0). Call train() and add()
            to populate it.

        Notes
        -----
        Factory strings provide a declarative way to specify index configurations.
        Time complexity: O(1) for index creation (training and adding vectors
        are separate operations). The factory string is parsed to determine the
        appropriate index type and parameters.
        """
        ...

    def write_index(self, index: FaissIndex, path: str | PathLike[str]) -> None:
        """Persist an index to disk.

        Extended Summary
        ----------------
        Serializes a FAISS index to a file on disk. This allows saving trained
        and populated indexes for later use without rebuilding. The index can
        be loaded later using read_index(). Useful for production deployments
        where indexes are built once and reused.

        Parameters
        ----------
        index : FaissIndex
            FAISS index instance to serialize. The index can be trained or untrained,
            populated or empty.
        path : str | PathLike[str]
            File path where the index will be written. The file format is FAISS-specific
            binary format. Existing files are overwritten.

        Notes
        -----
        Serialization includes the index structure, trained parameters (if applicable),
        and all stored vectors. File size depends on index type and ntotal. Time
        complexity: O(ntotal * d) for writing vectors. This operation performs
        file I/O and may take time for large indexes.
        """
        ...

    def read_index(self, path: str | PathLike[str]) -> FaissIndex:
        """Load an index from disk.

        Extended Summary
        ----------------
        Deserializes a FAISS index from a file previously written with write_index().
        This allows loading pre-built indexes without retraining or re-adding vectors.
        The loaded index is ready for search operations (if it was populated when saved).

        Parameters
        ----------
        path : str | PathLike[str]
            File path to the serialized FAISS index file. The file must exist
            and be a valid FAISS index format.

        Returns
        -------
        FaissIndex
            Loaded FAISS index instance. The index retains its trained state and
            all stored vectors (ntotal matches the saved value). Ready for search()
            operations if vectors were present when saved.

        Notes
        -----
        Loading restores the complete index state including structure, trained
        parameters, and vectors. Time complexity: O(file_size) for I/O plus
        O(ntotal * d) for deserializing vectors. This operation performs file I/O
        and may take time for large indexes. Raises IOError if the file doesn't
        exist or is corrupted.
        """
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

        Extended Summary
        ----------------
        Computes the norm (typically L2/Euclidean norm) along the specified axis
        of a float32 array. Used for vector normalization and distance computations
        in embedding operations.

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
            depends on input shape and keepdims parameter. This protocol method
            raises NotImplementedError and must be implemented by concrete classes.

        Raises
        ------
        NotImplementedError
            This is a protocol stub method that must be implemented by concrete classes.
        """
        del self, array, axis, keepdims
        raise NotImplementedError


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
