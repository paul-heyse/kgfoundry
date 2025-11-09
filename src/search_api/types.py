"""Vector search protocols and typed result structures.

This module defines PEP 544 protocols for FAISS-compatible vector search
and typed result structures using TypedDict/dataclass. All protocols and
types are fully typed to enable Pyright and Pyrefly strict checking.

Examples
--------
>>> from kgfoundry.search_api.types import VectorSearchResult, FaissIndexProtocol
>>> from numpy.typing import NDArray
>>> import numpy as np
>>> # Protocol usage
>>> class MyIndex:
...     def add(self, vectors: NDArray[np.float32]) -> None: ...
...     def search(
...         self, vectors: NDArray[np.float32], k: int
...     ) -> tuple[NDArray[np.float32], NDArray[np.int64]]: ...
>>> # Verify protocol satisfaction
>>> def use_index(idx: FaissIndexProtocol) -> None:
...     vecs = np.array([[1.0, 2.0]], dtype=np.float32)
...     idx.add(vecs)
...     distances, indices = idx.search(vecs, k=5)
"""

# [nav:section public-api]

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from operator import attrgetter
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

import numpy as np

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.problem_details import JsonValue

if TYPE_CHECKING:
    from numpy.typing import NDArray


__all__ = [
    "AgentSearchQuery",
    "AgentSearchResponse",
    "BM25IndexProtocol",
    "FaissIndexProtocol",
    "FaissModuleProtocol",
    "GpuClonerOptionsProtocol",
    "GpuResourcesProtocol",
    "IndexArray",
    "SpladeEncoderProtocol",
    "VectorArray",
    "VectorSearchResult",
    "VectorSearchResultTypedDict",
    "wrap_faiss_module",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# Type aliases for numpy arrays
if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import numpy.typing as npt

    type VectorArray = npt.NDArray[np.float32]
    type IndexArray = npt.NDArray[np.int64]
else:  # pragma: no cover - runtime fallback for doc generation
    VectorArray = np.ndarray
    IndexArray = np.ndarray

with suppress(
    AttributeError, TypeError
):  # pragma: no cover - ndarray may forbid updates
    VectorArray.__doc__ = (
        "Type alias for float32 vector arrays used in FAISS operations.\n\n"
        "All vectors must be normalized to unit length for inner-product search.\n"
        "Dimensions are typically 2560 for dense embeddings or configurable for\n"
        "sparse representations."
    )

with suppress(
    AttributeError, TypeError
):  # pragma: no cover - ndarray may forbid updates
    IndexArray.__doc__ = (
        "Type alias for int64 index arrays used in FAISS search results.\n\n"
        "Index arrays contain row indices into the vector store, typically returned\n"
        "from search operations alongside distance/similarity scores."
    )


# [nav:anchor FaissIndexProtocol]
class FaissIndexProtocol(Protocol):
    """Protocol for FAISS-compatible vector indexes.

    This protocol defines the minimum interface required for vector search
    operations. Implementations may support additional features (GPU acceleration,
    quantization, etc.) but must satisfy these core methods.

    Performance expectations:
    - `add()`: O(n) where n is the number of vectors; may require training first
    - `search()`: O(k * log(n)) for approximate indexes; O(n) for exact search
    - Indexes are typically trained before adding vectors (not shown in protocol)

    Concurrency notes:
    - Index operations are not thread-safe; serialize access from multiple threads
    - GPU indexes may block the calling thread during kernel execution
    - For async code, run index operations in thread pools to avoid blocking

    Examples
    --------
    >>> import numpy as np
    >>> from kgfoundry.search_api.types import FaissIndexProtocol, VectorArray
    >>> class SimpleIndex:
    ...     def add(self, vectors: VectorArray) -> None:
    ...         self._vectors = vectors
    ...
    ...     def search(
    ...         self, vectors: VectorArray, k: int
    ...     ) -> tuple[NDArray[np.float32], NDArray[np.int64]]:
    ...         # Simple inner product search
    ...         scores = vectors @ self._vectors.T
    ...         indices = np.argsort(-scores, axis=1)[:, :k]
    ...         distances = np.take_along_axis(scores, indices, axis=1)
    ...         return distances.astype(np.float32), indices.astype(np.int64)
    >>> idx: FaissIndexProtocol = SimpleIndex()
    """

    def add(self, vectors: VectorArray) -> None:
        """Add vectors to the index.

        Adds vectors to the index for future search operations. Vectors must
        match the index dimension and be normalized to unit length for
        inner-product search.

        Parameters
        ----------
        vectors : VectorArray
            Array of shape (n_vectors, dimension) with float32 dtype.
            Vectors should be normalized to unit length for inner-product search.
        """
        ...

    def search(
        self, vectors: VectorArray, k: int
    ) -> tuple[NDArray[np.float32], NDArray[np.int64]]:
        """Search for nearest neighbors.

        Searches the index for the k nearest neighbors of each query vector.
        Returns similarity scores and indices for the top-k matches.

        Parameters
        ----------
        vectors : VectorArray
            Query vectors of shape (n_queries, dimension) with float32 dtype.
            Must be normalized to unit length for inner-product search.
        k : int
            Number of nearest neighbors to return per query.

        Returns
        -------
        tuple[NDArray[np.float32], NDArray[np.int64]]
            Tuple of (distances, indices) where:
            - distances: shape (n_queries, k) with similarity scores (higher is better for IP)
            - indices: shape (n_queries, k) with vector indices in the index

        Notes
        -----
        - For inner-product metrics, higher scores indicate better matches
        - Invalid indices (no match) are typically represented as -1
        - Search performance depends on index type (exact vs approximate)
        """
        ...

    def train(self, vectors: VectorArray) -> None:
        """Train the index with sample vectors (optional method).

        Some FAISS indexes (e.g., quantized indexes) require training before
        adding vectors. This method is optional - not all indexes support it.

        Parameters
        ----------
        vectors : VectorArray
            Training vectors of shape (n_train, dimension) with float32 dtype.

        Notes
        -----
        - Flat indexes (exact search) do not require training
        - Quantized indexes (IVF, PQ) require training before add()
        - Calling train() on a non-trainable index is a no-op
        """
        ...

    def add_with_ids(self, vectors: VectorArray, ids: IndexArray) -> None:
        """Add vectors with explicit IDs (optional method).

        Some FAISS indexes support adding vectors with explicit IDs rather than
        sequential indices. This method is optional - not all indexes support it.

        Parameters
        ----------
        vectors : VectorArray
            Vectors to add, shape (n_vectors, dimension) with float32 dtype.
        ids : IndexArray
            Explicit IDs for each vector, shape (n_vectors,) with int64 dtype.

        Notes
        -----
        - IndexIDMap2 wrapper enables add_with_ids for any base index
        - If not supported, use add() which assigns sequential IDs
        """
        ...


# [nav:anchor FaissModuleProtocol]
class FaissModuleProtocol(Protocol):
    """Protocol for FAISS module surface used by adapters.

    This protocol describes the subset of FAISS API used by kgfoundry
    adapters. It enables type checking and allows fallback implementations
    (e.g., `_SimpleFaissModule`) to satisfy the protocol.

    Attributes
    ----------
    metric_inner_product : int
        Constant for inner-product metric (used with index_factory).
    metric_l2 : int
        Constant for L2 distance metric (used with index_factory).
    index_flat_ip : Callable[[int], FaissIndexProtocol]
        Create a flat inner-product index.
    index_id_map2 : Callable[[FaissIndexProtocol], FaissIndexProtocol]
        Wrap an index with 64-bit ID mapping.
    normalize_l2 : Callable[[VectorArray], None]
        Normalize vectors to unit L2 norm in-place.

    Examples
    --------
    >>> from kgfoundry.search_api.types import FaissModuleProtocol, FaissIndexProtocol
    >>> class MockFaissModule:
    ...     METRIC_INNER_PRODUCT = 1
    ...
    ...     def IndexFlatIP(self, dimension: int) -> FaissIndexProtocol: ...
    ...     def write_index(self, index: FaissIndexProtocol, path: str) -> None: ...
    ...     def read_index(self, path: str) -> FaissIndexProtocol: ...
    ...     def normalize_L2(self, vectors: VectorArray) -> None: ...
    >>> module: FaissModuleProtocol = MockFaissModule()
    """

    metric_inner_product: int
    """Constant for inner-product metric (used with index_factory)."""

    metric_l2: int
    """Constant for L2 distance metric (used with index_factory)."""

    index_flat_ip: Callable[[int], FaissIndexProtocol]
    """Create a flat inner-product index."""

    def index_factory(
        self, dimension: int, factory_string: str, metric: int
    ) -> FaissIndexProtocol:
        """Create an index from a factory string.

        Constructs a FAISS index using a factory string description. Factory
        strings describe index configuration (e.g., "IVF8192,PQ64" for
        quantized indexes).

        Parameters
        ----------
        dimension : int
            Vector dimension.
        factory_string : str
            Factory description (e.g., "IVF8192,PQ64" for quantized index).
        metric : int
            Metric type (METRIC_INNER_PRODUCT or METRIC_L2).

        Returns
        -------
        FaissIndexProtocol
            Configured index instance.

        Examples
        --------
        >>> # Create quantized index for large-scale search
        >>> index = faiss.index_factory(2560, "OPQ64,IVF8192,PQ64", faiss.METRIC_INNER_PRODUCT)
        """
        ...

    index_id_map2: Callable[[FaissIndexProtocol], FaissIndexProtocol]
    """Wrap an index with 64-bit ID mapping."""

    def write_index(self, index: FaissIndexProtocol, path: str) -> None:
        """Persist an index to disk.

        Serializes a FAISS index to disk for later loading. The index format
        is FAISS-specific and not human-readable.

        Parameters
        ----------
        index : FaissIndexProtocol
            Index instance to save.
        path : str
            File path for the persisted index.
        """
        ...

    def read_index(self, path: str) -> FaissIndexProtocol:
        """Load an index from disk.

        Deserializes a FAISS index from disk. The index must have been saved
        using write_index() with a compatible FAISS version.

        Parameters
        ----------
        path : str
            File path to the persisted index.

        Returns
        -------
        FaissIndexProtocol
            Loaded index instance.
        """
        ...

    normalize_l2: Callable[[VectorArray], None]
    """Normalize vectors to unit length in-place."""


# [nav:anchor GpuResourcesProtocol]
class GpuResourcesProtocol(Protocol):
    """Protocol for FAISS GPU resources.

    This protocol describes the StandardGpuResources interface used for GPU
    index operations. Implementations manage GPU memory and resources.

    Examples
    --------
    >>> from kgfoundry.search_api.types import GpuResourcesProtocol
    >>> class MockGpuResources:
    ...     def __init__(self) -> None:
    ...         pass
    >>> resources: GpuResourcesProtocol = MockGpuResources()
    """

    def __init__(self) -> None: ...


# [nav:anchor GpuClonerOptionsProtocol]
class GpuClonerOptionsProtocol(Protocol):
    """Protocol for FAISS GPU cloner options.

    This protocol describes the GpuClonerOptions interface used when cloning
    CPU indexes to GPU. The `use_cuvs` attribute controls cuVS acceleration.

    Attributes
    ----------
    use_cuvs : bool
        Enable cuVS acceleration for GPU operations (default: False).

    Examples
    --------
    >>> from kgfoundry.search_api.types import GpuClonerOptionsProtocol
    >>> class MockGpuClonerOptions:
    ...     use_cuvs: bool = False
    >>> options: GpuClonerOptionsProtocol = MockGpuClonerOptions()
    >>> options.use_cuvs = True
    """

    use_cuvs: bool
    """Enable cuVS acceleration for GPU operations (default: False)."""


@dataclass(frozen=True, slots=True)
# [nav:anchor VectorSearchResult]
class VectorSearchResult:
    """Typed result from vector search operations.

    This dataclass represents a single search result with typed fields
    and performance metadata. Results are immutable to prevent accidental
    modification.

    Attributes
    ----------
    doc_id : str
        Document identifier (URN format).
    chunk_id : str
        Chunk identifier within the document.
    score : float
        Final relevance score (may combine multiple signals).
    vector_score : float
        Raw vector similarity score (inner product or L2 distance).

    Examples
    --------
    >>> from kgfoundry.search_api.types import VectorSearchResult
    >>> result = VectorSearchResult(
    ...     doc_id="urn:doc:abc123",
    ...     chunk_id="urn:chunk:abc123:0-500",
    ...     score=0.95,
    ...     vector_score=0.95,
    ... )
    >>> assert result.score == 0.95
    """

    doc_id: str
    """Document identifier (URN format).

    Alias: none; name ``doc_id``.
    """

    chunk_id: str
    """Chunk identifier within the document.

    Alias: none; name ``chunk_id``.
    """

    score: float
    """Final relevance score.

    Alias: none; name ``score``.
    """

    vector_score: float
    """Vector similarity score.

    Alias: none; name ``vector_score``.
    """

    def __post_init__(self) -> None:
        """Validate result fields.

        This method is called automatically by dataclass after initialization. For frozen
        dataclasses, fields cannot be modified, so validation is limited to type checking (enforced
        by the type checker).
        """
        # Dataclass types are enforced at construction time, so runtime validation
        # is primarily for documentation. The type checker ensures correct usage.


# [nav:anchor SpladeEncoderProtocol]
class SpladeEncoderProtocol(Protocol):
    """Protocol for SPLADE encoder implementations.

    SPLADE (Sparse Lexical and Expansion) encoders transform text into
    sparse vector representations suitable for semantic search. This protocol
    defines the interface required for SPLADE-based search operations.

    Examples
    --------
    >>> from kgfoundry.search_api.types import SpladeEncoderProtocol, VectorArray
    >>> import numpy as np
    >>> class MySpladeEncoder:
    ...     def encode(self, texts: Sequence[str]) -> VectorArray:
    ...         # Return sparse vectors for input texts
    ...         return np.array([[0.1, 0.0, 0.5]], dtype=np.float32)
    >>> encoder: SpladeEncoderProtocol = MySpladeEncoder()
    >>> vecs = encoder.encode(["query text"])
    >>> assert vecs.shape[0] == 1
    """

    def encode(self, texts: Sequence[str]) -> VectorArray:
        """Encode text sequences into sparse vector representations.

        Transforms input text sequences into sparse vectors suitable for
        semantic search. Vectors are typically sparse (many zeros) and
        represent term importance in the vocabulary.

        Parameters
        ----------
        texts : Sequence[str]
            Input text sequences to encode.

        Returns
        -------
        VectorArray
            Sparse vector array of shape (len(texts), vocab_size) with float32 dtype.
            Vectors are typically sparse (many zeros) and represent term importance.
        """
        ...


# [nav:anchor BM25IndexProtocol]
class BM25IndexProtocol(Protocol):
    """Protocol for BM25 lexical search index implementations.

    BM25 indexes provide term-frequency based lexical search over document
    collections. This protocol defines the interface required for BM25-based
    search operations.

    Examples
    --------
    >>> from kgfoundry.search_api.types import BM25IndexProtocol
    >>> class MyBM25Index:
    ...     def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
    ...         # Return (doc_id, score) tuples
    ...         return [("doc1", 0.95), ("doc2", 0.87)]
    >>> index: BM25IndexProtocol = MyBM25Index()
    >>> results = index.search("search query", k=5)
    >>> assert len(results) <= 5
    """

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Search the index for documents matching the query.

        Searches the BM25 index for documents matching the query string.
        Returns top-k results sorted by relevance score.

        Parameters
        ----------
        query : str
            Search query string (will be tokenized internally).
        k : int, optional
            Maximum number of results to return. Defaults to 10.

        Returns
        -------
        list[tuple[str, float]]
            List of (document_id, score) tuples, sorted by score descending.
            Scores are BM25 relevance scores (higher is better).
        """
        ...


@dataclass(frozen=True, slots=True)
# [nav:anchor AgentSearchQuery]
class AgentSearchQuery:
    """Query parameters for agent catalog search operations.

    This dataclass represents a search query with typed fields for query text,
    result count, filtering facets, and explanation flags. All fields are
    validated at construction time.

    Attributes
    ----------
    query : str
        Search query text (tokenized and normalized internally). Cannot be empty.
    k : int
        Maximum number of results to return. Must be positive.
    facets : Mapping[str, str] | None
        Optional facet filters for narrowing search results. Common facets include:
        package, module, kind, stability, deprecated. Values are matched exactly
        (case-sensitive).
    explain : bool
        Whether to include explanation metadata in results. When True, results include
        detailed scoring breakdowns and match highlights.

    Examples
    --------
    >>> from kgfoundry.search_api.types import AgentSearchQuery
    >>> query = AgentSearchQuery(
    ...     query="vector store",
    ...     k=10,
    ...     facets={"package": "search_api"},
    ...     explain=True,
    ... )
    >>> assert query.k == 10
    >>> assert query.facets["package"] == "search_api"
    """

    query: str
    """Search query text.

    Alias: none; name ``query``.
    """

    k: int = 10
    """Maximum number of results to return.

    Must be positive and typically bounded (for example, ``1 <= k <= 100``).

    Alias: none; name ``k``.
    """

    facets: Mapping[str, str] | None = None
    """Optional facet filters for narrowing search results.

    Common facets include ``package``, ``module``, ``kind``, ``stability``, and ``deprecated``.
    Values are matched exactly (case-sensitive).

    Alias: none; name ``facets``.
    """

    explain: bool = False
    """Whether to include explanation metadata in results.

    When ``True``, results include detailed scoring breakdowns and match highlights for debugging and
    transparency.

    Alias: none; name ``explain``.
    """

    def __post_init__(self) -> None:
        """Validate query parameters.

        Ensures query text is non-empty and k is positive. Called automatically
        by dataclass after initialization.

        Raises
        ------
        ValueError
            If query is empty or k is not positive.
        """
        if not self.query.strip():
            msg = "Query text cannot be empty"
            raise ValueError(msg)
        if self.k <= 0:
            msg = f"k must be positive, got {self.k}"
            raise ValueError(msg)


# [nav:anchor VectorSearchResultTypedDict]
class VectorSearchResultTypedDict(TypedDict, total=True):
    """TypedDict representation of vector search results.

    This TypedDict represents a search result from the agent catalog with
    symbol metadata, relevance scores, and source anchors. Used for JSON
    serialization and API responses.

    Attributes
    ----------
    symbol_id : str
        Fully qualified symbol identifier (e.g., 'py:module.Class.method').
    score : float
        Final relevance score combining lexical and vector signals.
    lexical_score : float
        BM25 lexical search score (0.0 to 1.0).
    vector_score : float
        Vector similarity score from dense/sparse search (0.0 to 1.0).
    package : str
        Package name containing the symbol.
    module : str
        Module name containing the symbol.
    qname : str
        Qualified name of the symbol within its module.
    kind : str
        Symbol kind (e.g., 'class', 'function', 'module').
    anchor : Mapping[str, int | None]
        Source anchor metadata (start_line, end_line, etc.).
    metadata : Mapping[str, JsonValue]
        Additional metadata (stability, deprecated, summary, etc.).
    """

    symbol_id: str
    """Fully qualified symbol identifier (e.g., 'py:module.Class.method')."""

    score: float
    """Final relevance score combining lexical and vector signals."""

    lexical_score: float
    """BM25 lexical search score (0.0 to 1.0)."""

    vector_score: float
    """Vector similarity score from dense/sparse search (0.0 to 1.0)."""

    package: str
    """Package name containing the symbol."""

    module: str
    """Module name containing the symbol."""

    qname: str
    """Qualified name of the symbol within its module."""

    kind: str
    """Symbol kind (e.g., 'class', 'function', 'module')."""

    anchor: Mapping[str, int | None]
    """Source anchor metadata (start_line, end_line, etc.)."""

    metadata: Mapping[str, JsonValue]
    """Additional metadata (stability, deprecated, summary, etc.)."""


# [nav:anchor AgentSearchResponse]
class AgentSearchResponse(TypedDict, total=True):
    """TypedDict representation of agent catalog search response.

    This TypedDict represents a complete search response from the agent catalog
    with results, metadata, and performance metrics. Used for JSON serialization
    and API responses.

    Attributes
    ----------
    results : list[VectorSearchResultTypedDict]
        List of search results, sorted by score descending.
    total : int
        Total number of results (may exceed len(results) if truncated).
    took_ms : int
        Query execution time in milliseconds.
    metadata : Mapping[str, JsonValue]
        Response metadata (alpha, backend, query_info, etc.).
    """

    results: list[VectorSearchResultTypedDict]
    """List of search results, sorted by score descending."""

    total: int
    """Total number of results (may exceed len(results) if truncated)."""

    took_ms: int
    """Query execution time in milliseconds."""

    metadata: Mapping[str, JsonValue]
    """Response metadata (alpha, backend, query_info, etc.)."""


class _LegacyFaissModule(Protocol):
    """Subset of the legacy FAISS module surface used by the adapter."""

    METRIC_INNER_PRODUCT: int
    METRIC_L2: int

    index_factory: Callable[[int, str, int], FaissIndexProtocol]
    write_index: Callable[[FaissIndexProtocol, str], None]
    read_index: Callable[[str], FaissIndexProtocol]


def _labels_or_default(labelnames: Sequence[str] | None) -> Sequence[str]:
    return tuple(labelnames) if labelnames is not None else ()


def _legacy_index_flat_ip(
    module: _LegacyFaissModule,
) -> Callable[[int], FaissIndexProtocol]:
    attr_any: object = attrgetter("IndexFlatIP")(module)
    if not callable(attr_any):  # pragma: no cover - defensive guard for type checkers
        msg = "Legacy FAISS module attribute 'IndexFlatIP' must be callable"
        raise TypeError(msg)
    return cast("Callable[[int], FaissIndexProtocol]", attr_any)


def _legacy_index_id_map2(
    module: _LegacyFaissModule,
) -> Callable[[FaissIndexProtocol], FaissIndexProtocol]:
    attr_any: object = attrgetter("IndexIDMap2")(module)
    if not callable(attr_any):  # pragma: no cover - defensive guard for type checkers
        msg = "Legacy FAISS module attribute 'IndexIDMap2' must be callable"
        raise TypeError(msg)
    return cast("Callable[[FaissIndexProtocol], FaissIndexProtocol]", attr_any)


def _legacy_normalize_l2(module: _LegacyFaissModule) -> Callable[[VectorArray], None]:
    attr_any: object = attrgetter("normalize_L2")(module)
    if not callable(attr_any):  # pragma: no cover - defensive guard for type checkers
        msg = "Legacy FAISS module attribute 'normalize_L2' must be callable"
        raise TypeError(msg)
    return cast("Callable[[VectorArray], None]", attr_any)


class _FaissModuleAdapter:
    """Adapter that exposes PEP 8 method names for FAISS modules.

    Initializes adapter with legacy FAISS module.

    Parameters
    ----------
    module : _LegacyFaissModule
        Legacy FAISS module with UPPER_CASE names.
    """

    def __init__(self, module: _LegacyFaissModule) -> None:
        self._module = module

    @property
    def metric_inner_product(self) -> int:
        """Return inner product metric constant."""
        return self._module.METRIC_INNER_PRODUCT

    @property
    def metric_l2(self) -> int:
        """Return L2 metric constant."""
        return self._module.METRIC_L2

    def index_flat_ip(self, dimension: int) -> FaissIndexProtocol:
        """Create flat inner product index.

        Parameters
        ----------
        dimension : int
            Vector dimension.

        Returns
        -------
        FaissIndexProtocol
            FAISS index instance.
        """
        constructor = _legacy_index_flat_ip(self._module)
        return constructor(dimension)

    def index_factory(
        self, dimension: int, factory_string: str, metric: int
    ) -> FaissIndexProtocol:
        """Create index from factory string.

        Parameters
        ----------
        dimension : int
            Vector dimension.
        factory_string : str
            Factory description string.
        metric : int
            Distance metric constant.

        Returns
        -------
        FaissIndexProtocol
            FAISS index instance.
        """
        return self._module.index_factory(dimension, factory_string, metric)

    def index_id_map2(self, index: FaissIndexProtocol) -> FaissIndexProtocol:
        """Wrap index with 64-bit ID mapping.

        Parameters
        ----------
        index : FaissIndexProtocol
            Base index to wrap.

        Returns
        -------
        FaissIndexProtocol
            Index with ID mapping.
        """
        wrapper = _legacy_index_id_map2(self._module)
        return wrapper(index)

    def write_index(self, index: FaissIndexProtocol, path: str) -> None:
        """Write index to disk.

        Parameters
        ----------
        index : FaissIndexProtocol
            Index to serialize.
        path : str
            Output file path.
        """
        self._module.write_index(index, path)

    def read_index(self, path: str) -> FaissIndexProtocol:
        """Read index from disk.

        Parameters
        ----------
        path : str
            Input file path.

        Returns
        -------
        FaissIndexProtocol
            Loaded index instance.
        """
        return self._module.read_index(path)

    def normalize_l2(self, vectors: VectorArray) -> None:
        """Normalize vectors to unit length in-place.

        Parameters
        ----------
        vectors : VectorArray
            Vector array to normalize (modified in-place).
        """
        normalizer = _legacy_normalize_l2(self._module)
        normalizer(vectors)

    def __getattr__(self, name: str) -> object:
        """Get attribute with legacy name fallback.

        Parameters
        ----------
        name : str
            Attribute name.

        Returns
        -------
        object
            Attribute value from module.
        """
        if name == "METRIC_INNER_PRODUCT":
            return self.metric_inner_product
        if name == "METRIC_L2":
            return self.metric_l2
        if name == "IndexFlatIP":
            return self.index_flat_ip
        if name == "IndexIDMap2":
            return self.index_id_map2
        if name == "normalize_L2":
            return self.normalize_l2
        return cast("object", getattr(self._module, name))


# [nav:anchor wrap_faiss_module]
def wrap_faiss_module(module: object) -> FaissModuleProtocol:
    """Return a :class:`FaissModuleProtocol` with PEP 8 method names.

    Parameters
    ----------
    module : object
        FAISS module to wrap.

    Returns
    -------
    FaissModuleProtocol
        Wrapped module conforming to protocol.
    """
    required_attributes = (
        "index_flat_ip",
        "index_factory",
        "index_id_map2",
        "write_index",
        "read_index",
        "normalize_l2",
    )
    if all(hasattr(module, attribute) for attribute in required_attributes):
        return cast("FaissModuleProtocol", module)
    legacy_module = cast("_LegacyFaissModule", module)
    return cast("FaissModuleProtocol", _FaissModuleAdapter(legacy_module))
