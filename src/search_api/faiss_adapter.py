"""FAISS adapter with typed GPU fallbacks and DuckDB integration."""

# [nav:section public-api]

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, ClassVar, Final, TypeGuard, cast

from kgfoundry_common.errors import IndexBuildError, VectorSearchError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.numpy_typing import (
    normalize_l2,
    topk_indices,
)
from kgfoundry_common.typing import gate_import
from registry.duckdb_helpers import fetch_all, fetch_one
from search_api.faiss_gpu import (
    clone_index_to_gpu,
    configure_search_parameters,
    detect_gpu_context,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    import numpy.typing as npt
    from numpy.typing import NDArray

    from kgfoundry_common.numpy_typing import (
        FloatMatrix,
        FloatVector,
        IntVector,
    )
    from search_api.faiss_gpu import (
        GpuContext,
    )
    from search_api.types import FaissIndexProtocol, FaissModuleProtocol

    type FloatArray = npt.NDArray[np.float32]
    type IntArray = npt.NDArray[np.int64]
    type StrArray = npt.NDArray[np.str_]
    type VecArray = npt.NDArray[np.float32]
else:  # pragma: no cover - runtime fallback
    np = gate_import("numpy", "FAISS adapter vector helpers")
    FloatArray = np.ndarray
    IntArray = np.ndarray
    StrArray = np.ndarray
    VecArray = np.ndarray

__all__ = [
    "DenseVecs",
    "FaissAdapter",
    "FloatArray",
    "IntArray",
    "StrArray",
    "VecArray",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _duckdb_module() -> ModuleType:
    """Return duckdb module resolved lazily for FAISS adapter usage.

    Returns
    -------
    ModuleType
        Imported :mod:`duckdb` module reference.
    """
    return cast("ModuleType", gate_import("duckdb", "FAISS adapter index hydration"))


def _is_faiss_index(candidate: object) -> TypeGuard[FaissIndexProtocol]:
    """Return True when ``candidate`` exposes the FAISS index protocol surface.

    Parameters
    ----------
    candidate : object
        Candidate object to check.

    Returns
    -------
    TypeGuard[FaissIndexProtocol]
        True if candidate matches the protocol.
    """
    if candidate is None:
        return False

    required_methods = ("search", "add", "train", "add_with_ids")
    for method in required_methods:
        attribute: object | None = getattr(candidate, method, None)
        if attribute is None or not callable(attribute):
            return False
    return True


def _as_optional_str(value: object) -> str:
    """Convert a value to a string, handling None and non-string types.

    Extended Summary
    ----------------
    Normalizes database query results to strings for consistent processing in
    FAISS adapter index loading. Handles None values by returning empty strings,
    preserves string values unchanged, and converts other types via str().
    This helper ensures type safety when reading from DuckDB which may return
    various types (str, None, int, etc.) for text fields.

    Parameters
    ----------
    value : object
        Value to convert. May be str, None, or any other type.

    Returns
    -------
    str
        String representation of the value. Empty string if value is None.

    Notes
    -----
    Time O(1) for strings and None; O(n) for other types where n is the
    string representation length. This function is internal to FAISS adapter
    index loading and should not be used outside this module.

    Examples
    --------
    >>> _as_optional_str("hello")
    'hello'
    >>> _as_optional_str(None)
    ''
    >>> _as_optional_str(123)
    '123'
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


MIN_FACTORY_DIMENSION: Final[int] = 64

LoadLibraryFn = Callable[..., None]


def _load_libcuvs() -> LoadLibraryFn | None:
    """Attempt to load cuVS library loader function for GPU acceleration.

    Extended Summary
    ----------------
    Tries to import cuVS library modules (libcuvs or libcuvs_cu13) and extract
    the load_library function. cuVS provides GPU-accelerated vector search
    operations that can be used as a drop-in replacement for FAISS GPU
    operations. This function enables optional GPU acceleration when cuVS is
    available, falling back gracefully to CPU/FAISS when it is not.

    Returns
    -------
    LoadLibraryFn | None
        Callable load_library function if cuVS module is found and provides it,
        None otherwise. The function can be called to initialize cuVS runtime.

    Notes
    -----
    Time O(1) amortized after first call (uses lru_cache). Side effects: may
    attempt to import optional modules. This function is called at module load
    time to detect cuVS availability. Failures are logged at debug level and
    do not prevent FAISS adapter from functioning (falls back to CPU/FAISS).

    Examples
    --------
    >>> loader = _load_libcuvs()
    >>> if loader is not None:
    ...     loader()  # Initialize cuVS runtime
    """
    module_names = ("libcuvs", "libcuvs_cu13")
    module = None
    for name in module_names:
        try:
            module = importlib.import_module(name)
        except (
            ImportError,
            ModuleNotFoundError,
        ):  # pragma: no cover - optional dependency
            continue
        except (RuntimeError, OSError):  # pragma: no cover - optional dependency
            logger.debug("Failed to import %s: runtime error", name)
            continue
        else:
            break

    if module is None:
        return None

    if hasattr(module, "load_library"):
        candidate: object = module.load_library
        if callable(candidate):
            return cast("LoadLibraryFn", candidate)
    return None


_typed_load_cuvs = _load_libcuvs()
if _typed_load_cuvs is not None:  # pragma: no cover - optional dependency
    _typed_load_cuvs()
else:  # pragma: no cover - optional dependency
    logger.debug("cuVS library not available; continuing with FAISS CPU helpers")


def _load_faiss_module() -> FaissModuleProtocol | None:
    """Attempt to load FAISS module for vector search operations.

    Extended Summary
    ----------------
    Tries to import the FAISS (Facebook AI Similarity Search) module which
    provides efficient vector similarity search implementations. FAISS is an
    optional dependency; if unavailable, the adapter falls back to CPU-based
    search using NumPy. This function enables graceful degradation when FAISS
    is not installed or fails to load.

    Returns
    -------
    FaissModuleProtocol | None
        FAISS module instance if import succeeds, None otherwise. The module
        provides index construction and search methods.

    Notes
    -----
    Time O(1) amortized after first call (uses lru_cache). Side effects: may
    attempt to import optional FAISS module. Failures are logged at debug level
    and do not prevent adapter from functioning (falls back to NumPy-based
    search). This function is called at module load time to detect FAISS
    availability.

    Examples
    --------
    >>> faiss_module = _load_faiss_module()
    >>> if faiss_module is not None:
    ...     index = faiss_module.IndexFlatIP(128)
    """
    try:  # pragma: no cover - optional dependency
        module = importlib.import_module("faiss")
    except (
        ImportError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as exc:  # pragma: no cover - optional dependency
        logger.debug("FAISS import failed: %s", exc, exc_info=True)
        return None
    return cast("FaissModuleProtocol", module)


faiss = _load_faiss_module()
HAVE_FAISS = faiss is not None


@dataclass(frozen=True)
# [nav:anchor DenseVecs]
class DenseVecs:
    """Dense vector matrix and ID mapping used to seed FAISS indexes."""

    ids: list[str]
    matrix: FloatMatrix


@dataclass(slots=True, frozen=True)
class FaissAdapterConfig:
    """Configuration options for :class:`FaissAdapter`."""

    factory: str = "OPQ64,IVF8192,PQ64"
    metric: str = "ip"
    nprobe: int = 64
    use_gpu: bool = True
    use_cuvs: bool = True
    gpu_devices: Sequence[int] | None = None


# [nav:anchor FaissAdapter]
class FaissAdapter:
    """Build FAISS indexes with optional GPU acceleration and CPU fallback.

    Extended Summary
    ----------------
    Provides a typed interface for building and querying FAISS vector indexes
    with support for GPU acceleration (via FAISS GPU or cuVS) and graceful
    CPU fallback. Loads vectors from DuckDB catalog, builds indexes using
    configurable factory strings (e.g., "OPQ64,IVF8192,PQ64"), and provides
    search operations with ID mapping. Supports both modern config-based API
    and legacy keyword arguments for backward compatibility.

    Parameters
    ----------
    db_path : str
        Path to DuckDB database file containing vectors dataset and metadata.
    config : FaissAdapterConfig | None, optional
        Configuration object with factory, metric, nprobe, GPU settings.
        If None, uses default config or legacy_options. Defaults to None.
    **legacy_options : object
        Legacy keyword arguments for backward compatibility. Valid keys:
        factory (str), metric (str), nprobe (int), use_gpu (bool),
        use_cuvs (bool), gpu_devices (Sequence[int] | None). Cannot be used
        together with config parameter.

    Notes
    -----
    Time O(1) for initialization. The index is not built until build() is called.
    GPU acceleration requires FAISS GPU or cuVS libraries and appropriate CUDA
    runtime. Falls back to CPU/NumPy search if GPU libraries are unavailable.
    Configuration validation ensures factory/metric compatibility and prevents
    mixing config and legacy_options.

    Examples
    --------
    >>> adapter = FaissAdapter(
    ...     "/data/catalog.duckdb", config=FaissAdapterConfig(factory="Flat", metric="ip")
    ... )
    >>> adapter.build()
    >>> results = adapter.search(vectors, k=10)
    """

    _CONFIG_FIELDS: ClassVar[set[str]] = {
        "factory",
        "metric",
        "nprobe",
        "use_gpu",
        "use_cuvs",
        "gpu_devices",
    }

    def __init__(
        self,
        db_path: str,
        *,
        config: FaissAdapterConfig | None = None,
        **legacy_options: object,
    ) -> None:
        self.db_path = db_path
        resolved_config = self._resolve_config(config, legacy_options)
        self.factory = resolved_config.factory
        self.metric = resolved_config.metric
        self.nprobe = resolved_config.nprobe
        self.use_gpu = resolved_config.use_gpu
        self.use_cuvs = resolved_config.use_cuvs
        devices = resolved_config.gpu_devices or (0,)
        self._gpu_devices = tuple(int(device) for device in devices)

        self.index: FaissIndexProtocol | None = None
        self.idmap: list[str] | None = None
        self.vecs: DenseVecs | None = None

        self._cpu_matrix: FloatMatrix | None = None
        self._gpu_context: GpuContext | None = None

    @property
    def cpu_matrix(self) -> FloatMatrix | None:
        """Return the CPU-resident vector matrix when available."""
        return self._cpu_matrix

    @classmethod
    def _resolve_config(
        cls, config: FaissAdapterConfig | None, legacy_options: dict[str, object]
    ) -> FaissAdapterConfig:
        """Resolve configuration from config object or legacy keyword arguments.

        Extended Summary
        ----------------
        Validates that config and legacy_options are not mixed, then returns
        the appropriate configuration. If config is provided, returns it directly.
        Otherwise, validates legacy_options keys and converts them to a config
        object. If neither is provided, returns default config.

        Parameters
        ----------
        config : FaissAdapterConfig | None
            Modern config object. If provided, used directly.
        legacy_options : dict[str, object]
            Legacy keyword arguments dictionary. Validated and converted to config.

        Returns
        -------
        FaissAdapterConfig
            Resolved configuration object ready for use.

        Notes
        -----
        Time O(n) where n is the number of legacy_options keys. This method
        enforces the API contract that config and legacy_options cannot be mixed.
        """
        cls._ensure_config_not_mixed(config, legacy_options)
        if config is not None:
            return config

        cls._validate_legacy_keys(legacy_options)
        if not legacy_options:
            return FaissAdapterConfig()
        return cls._config_from_legacy_options(legacy_options)

    @classmethod
    def _ensure_config_not_mixed(
        cls, config: FaissAdapterConfig | None, legacy_options: dict[str, object]
    ) -> None:
        """Ensure config and legacy_options are not provided simultaneously.

        Extended Summary
        ----------------
        Validates that the caller has not provided both a modern config object
        and legacy keyword arguments. This prevents API confusion and ensures
        clear configuration precedence.

        Parameters
        ----------
        config : FaissAdapterConfig | None
            Modern config object (may be None).
        legacy_options : dict[str, object]
            Legacy keyword arguments dictionary (may be empty).

        Raises
        ------
        TypeError
            If both config and legacy_options are provided (non-None config and
            non-empty legacy_options).

        Notes
        -----
        Time O(1). This validation ensures API clarity and prevents ambiguous
        configuration precedence.
        """
        if config is None or not legacy_options:
            return
        unexpected = ", ".join(sorted(legacy_options))
        message = (
            f"FaissAdapter received both 'config' and individual keyword options: {unexpected}"
        )
        raise TypeError(message)

    @classmethod
    def _validate_legacy_keys(cls, legacy_options: dict[str, object]) -> None:
        """Validate that legacy_options contains only known configuration keys.

        Extended Summary
        ----------------
        Checks that all keys in legacy_options are valid configuration fields
        (factory, metric, nprobe, use_gpu, use_cuvs, gpu_devices). Raises
        TypeError if any unexpected keys are found.

        Parameters
        ----------
        legacy_options : dict[str, object]
            Legacy keyword arguments dictionary to validate.

        Raises
        ------
        TypeError
            If legacy_options contains keys not in _CONFIG_FIELDS.

        Notes
        -----
        Time O(n) where n is the number of keys in legacy_options. This
        validation provides clear error messages for typos or invalid options.
        """
        unexpected_keys = set(legacy_options) - cls._CONFIG_FIELDS
        if not unexpected_keys:
            return
        unexpected = ", ".join(sorted(unexpected_keys))
        message = f"FaissAdapter got unexpected keyword arguments: {unexpected}"
        raise TypeError(message)

    @classmethod
    def _config_from_legacy_options(cls, legacy_options: dict[str, object]) -> FaissAdapterConfig:
        """Convert legacy keyword arguments to FaissAdapterConfig.

        Extended Summary
        ----------------
        Extracts configuration values from legacy_options dictionary, applies
        type coercion for each field, and constructs a FaissAdapterConfig instance.
        Uses default values from base config for missing fields. This method
        bridges the legacy keyword argument API to the modern config-based API.

        Parameters
        ----------
        legacy_options : dict[str, object]
            Legacy keyword arguments dictionary. Expected keys: factory (str),
            metric (str), nprobe (int), use_gpu (bool), use_cuvs (bool),
            gpu_devices (Sequence[int] | None).

        Returns
        -------
        FaissAdapterConfig
            Configuration object with coerced values from legacy_options.

        Notes
        -----
        Time O(n) where n is the number of fields. Type coercion ensures type
        safety while allowing flexible input types (e.g., int/float for nprobe).
        Missing fields use defaults from FaissAdapterConfig(). TypeError may be
        raised by helper methods (_coerce_str, _coerce_int, _coerce_bool,
        _coerce_gpu_devices) if field values cannot be coerced to expected types.
        """
        base = FaissAdapterConfig()
        options = {
            field: legacy_options[field] for field in cls._CONFIG_FIELDS if field in legacy_options
        }
        factory = cls._coerce_str(options.get("factory", base.factory), "factory")
        metric = cls._coerce_str(options.get("metric", base.metric), "metric")
        nprobe = cls._coerce_int(options.get("nprobe", base.nprobe), "nprobe")
        use_gpu = cls._coerce_bool(options.get("use_gpu", base.use_gpu), "use_gpu")
        use_cuvs = cls._coerce_bool(options.get("use_cuvs", base.use_cuvs), "use_cuvs")
        gpu_devices_option = options.get("gpu_devices", base.gpu_devices)
        gpu_devices = cls._coerce_gpu_devices(gpu_devices_option)
        return FaissAdapterConfig(
            factory=factory,
            metric=metric,
            nprobe=nprobe,
            use_gpu=use_gpu,
            use_cuvs=use_cuvs,
            gpu_devices=gpu_devices,
        )

    @staticmethod
    def _coerce_str(value: object, name: str) -> str:
        """Coerce value to string with validation.

        Extended Summary
        ----------------
        Validates that value is a string and returns it unchanged. Raises
        TypeError if value is not a string, providing a clear error message
        with the field name.

        Parameters
        ----------
        value : object
            Value to coerce. Must be a string.
        name : str
            Field name for error messages (e.g., "factory", "metric").

        Returns
        -------
        str
            String value unchanged.

        Raises
        ------
        TypeError
            If value is not a string.

        Notes
        -----
        Time O(1). This method provides strict type validation for string
        configuration fields, ensuring type safety in config construction.

        Examples
        --------
        >>> FaissAdapter._coerce_str("OPQ64", "factory")
        'OPQ64'
        >>> FaissAdapter._coerce_str(123, "factory")
        Traceback (most recent call last):
            ...
        TypeError: factory must be a string
        """
        if isinstance(value, str):
            return value
        message = f"{name} must be a string"
        raise TypeError(message)

    @staticmethod
    def _coerce_int(value: object, name: str) -> int:
        """Coerce value to integer with validation.

        Extended Summary
        ----------------
        Validates that value is an integer and returns it unchanged. Raises
        TypeError if value is not an integer, providing a clear error message
        with the field name.

        Parameters
        ----------
        value : object
            Value to coerce. Must be an integer.
        name : str
            Field name for error messages (e.g., "nprobe").

        Returns
        -------
        int
            Integer value unchanged.

        Raises
        ------
        TypeError
            If value is not an integer.

        Notes
        -----
        Time O(1). This method provides strict type validation for integer
        configuration fields, ensuring type safety in config construction.

        Examples
        --------
        >>> FaissAdapter._coerce_int(64, "nprobe")
        64
        >>> FaissAdapter._coerce_int("64", "nprobe")
        Traceback (most recent call last):
            ...
        TypeError: nprobe must be an integer
        """
        if isinstance(value, int):
            return value
        message = f"{name} must be an integer"
        raise TypeError(message)

    @staticmethod
    def _coerce_bool(value: object, name: str) -> bool:
        """Coerce value to boolean with validation.

        Extended Summary
        ----------------
        Validates that value is a boolean and returns it unchanged. Raises
        TypeError if value is not a boolean, providing a clear error message
        with the field name.

        Parameters
        ----------
        value : object
            Value to coerce. Must be a boolean.
        name : str
            Field name for error messages (e.g., "use_gpu", "use_cuvs").

        Returns
        -------
        bool
            Boolean value unchanged.

        Raises
        ------
        TypeError
            If value is not a boolean.

        Notes
        -----
        Time O(1). This method provides strict type validation for boolean
        configuration fields, ensuring type safety in config construction.

        Examples
        --------
        >>> FaissAdapter._coerce_bool(True, "use_gpu")
        True
        >>> FaissAdapter._coerce_bool(1, "use_gpu")
        Traceback (most recent call last):
            ...
        TypeError: use_gpu must be a boolean
        """
        if isinstance(value, bool):
            return value
        message = f"{name} must be a boolean"
        raise TypeError(message)

    @staticmethod
    def _coerce_gpu_devices(value: object) -> tuple[int, ...] | None:
        """Coerce value to GPU device tuple or None.

        Extended Summary
        ----------------
        Validates and converts value to a tuple of GPU device IDs. Returns None
        if value is None. Converts sequence elements to integers. Raises TypeError
        if value is not None and not a sequence.

        Parameters
        ----------
        value : object
            Value to coerce. May be None, sequence of integers, or other types.

        Returns
        -------
        tuple[int, ...] | None
            Tuple of GPU device IDs, or None if value is None.

        Raises
        ------
        TypeError
            If value is not None and not a sequence, or if sequence elements
            cannot be converted to integers.

        Notes
        -----
        Time O(n) where n is the length of the sequence. This method handles
        GPU device specification for multi-GPU setups, converting various input
        formats (list, tuple, etc.) to a consistent tuple[int, ...] type.

        Examples
        --------
        >>> FaissAdapter._coerce_gpu_devices([0, 1])
        (0, 1)
        >>> FaissAdapter._coerce_gpu_devices(None)
        >>> FaissAdapter._coerce_gpu_devices("invalid")
        Traceback (most recent call last):
            ...
        TypeError: gpu_devices must be a sequence of integers or None
        """
        if value is None:
            return None
        if not isinstance(value, Sequence):
            message = "gpu_devices must be a sequence of integers or None"
            raise TypeError(message)
        return tuple(int(device) for device in value)

    def build(self) -> None:
        """Build or rebuild the FAISS index from persisted vectors.

        Raises
        ------
        IndexBuildError
            If index construction fails.

        Notes
        -----
        Propagates :class:`VectorSearchError` when vector loading fails prior to
        index construction.
        """
        vectors = self._load_dense_vectors()
        self.vecs = vectors
        self.idmap = vectors.ids
        self._cpu_matrix = vectors.matrix

        module = faiss
        if not HAVE_FAISS or module is None:
            logger.debug("FAISS unavailable; CPU search fallback will be used")
            self.index = None
            return
        faiss_module: FaissModuleProtocol = module

        try:
            dimension = vectors.matrix.shape[1]
            metric_type = self._resolve_metric(faiss_module)
            factory = self.factory if dimension >= MIN_FACTORY_DIMENSION else "Flat"

            cpu_index = faiss_module.index_factory(dimension, factory, metric_type)

            faiss_module.normalize_l2(vectors.matrix)
            cpu_index.train(vectors.matrix)

            id_array = cast("IntVector", np.arange(len(vectors.ids), dtype=np.int64))
            cpu_index.add_with_ids(vectors.matrix, id_array)

            gpu_context = None
            index: FaissIndexProtocol = cpu_index
            if self.use_gpu:
                gpu_context = detect_gpu_context(
                    faiss_module,
                    use_cuvs=self.use_cuvs,
                    device_ids=self._gpu_devices,
                )
                if gpu_context is not None:
                    index = clone_index_to_gpu(cpu_index, gpu_context)

            configure_search_parameters(
                faiss_module,
                index,
                nprobe=self.nprobe,
                gpu_enabled=gpu_context is not None,
            )
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Failed to build FAISS index: {exc}"
            raise IndexBuildError(msg) from exc

        if not _is_faiss_index(index):
            msg = "FAISS index failed protocol validation"
            raise IndexBuildError(msg)

        self.index = index
        self._gpu_context = gpu_context

    def load_or_build(self, cpu_index_path: str | None = None) -> None:
        """Load an existing CPU index or fall back to rebuilding from vectors.

        Parameters
        ----------
        cpu_index_path : str | None, optional
            Path to CPU index file.

        Notes
        -----
        Propagates :class:`VectorSearchError` when index or vector loading
        fails before a rebuild occurs.
        """
        module = faiss
        if module is None or not HAVE_FAISS:
            self.build()
            return
        faiss_module: FaissModuleProtocol = module

        if cpu_index_path:
            index_path = Path(cpu_index_path)
            if index_path.exists():
                try:
                    cpu_index = faiss_module.read_index(str(index_path))
                    vectors = self._load_dense_vectors()
                    self.vecs = vectors
                    self.idmap = vectors.ids
                    self._cpu_matrix = vectors.matrix

                    gpu_context = None
                    if self.use_gpu:
                        gpu_context = detect_gpu_context(
                            faiss_module,
                            use_cuvs=self.use_cuvs,
                            device_ids=self._gpu_devices,
                        )
                        if gpu_context is not None:
                            cpu_index = clone_index_to_gpu(cpu_index, gpu_context)
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                ) as exc:  # pragma: no cover - defensive fallback
                    logger.warning(
                        "Failed to load FAISS index from %s: %s",
                        index_path,
                        exc,
                        exc_info=True,
                    )
                else:
                    configure_search_parameters(
                        faiss_module,
                        cpu_index,
                        nprobe=self.nprobe,
                        gpu_enabled=gpu_context is not None,
                    )

                    if not _is_faiss_index(cpu_index):
                        logger.warning(
                            "Loaded FAISS index failed protocol validation; rebuilding",
                        )
                    else:
                        self.index = cpu_index
                        self._gpu_context = gpu_context
                        return

        self.build()

    def search(
        self, query: Sequence[float] | NDArray[np.float32], k: int
    ) -> list[tuple[str, float]]:
        """Return the top ``k`` vector matches for ``query``.

        Parameters
        ----------
        query : Sequence[float] | NDArray[np.float32]
            Query vector.
        k : int
            Number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            List of (doc_id, score) tuples sorted by score descending.

        Raises
        ------
        ValueError
            If k is not positive.
        RuntimeError
            If FAISS module is not available, index is not initialized, or ID map is missing.
        """
        if k <= 0:
            msg = "k must be positive"
            raise ValueError(msg)

        query_array = cast("FloatMatrix", np.asarray(query, dtype=np.float32).reshape(1, -1))
        normalized_query = normalize_l2(query_array, axis=1)

        module = faiss
        if module is not None and HAVE_FAISS:
            index_candidate = self._require_index()
            if self.idmap is None:
                msg = "ID map not initialized"
                raise RuntimeError(msg)

            distances_array, indices_array = index_candidate.search(normalized_query, k)
            distance_row = cast("FloatVector", distances_array[0])
            index_row = cast("IntVector", indices_array[0])
            index_list = cast("list[int]", index_row.tolist())
            score_list = cast("list[float]", distance_row.tolist())
            results: list[tuple[str, float]] = []
            for idx, score in zip(index_list, score_list, strict=False):
                if idx < 0 or idx >= len(self.idmap):
                    continue
                results.append((self.idmap[idx], float(score)))
            return results

        normalized_vector = cast("FloatVector", normalized_query[0])
        return self._cpu_search(normalized_vector, k)

    def save(self, index_uri: str, idmap_uri: str | None = None) -> None:
        """Persist the index (when available) and ID mapping to disk.

        Parameters
        ----------
        index_uri : str
            Path where the FAISS index will be saved.
        idmap_uri : str | None, optional
            Path where the ID mapping will be saved. If None, defaults to ``{index_uri}.ids.npy``.

        Raises
        ------
        RuntimeError
            If no vectors have been loaded.
        """
        if self.vecs is None:
            msg = "No vectors loaded; call build() before save()."
            raise RuntimeError(msg)

        idmap_path = Path(idmap_uri or f"{index_uri}.ids.npy")
        idmap_path.parent.mkdir(parents=True, exist_ok=True)
        idmap_array: StrArray = np.asarray(self.vecs.ids, dtype=np.str_)
        np.save(idmap_path, idmap_array)

        module = faiss
        if module is None or not HAVE_FAISS:
            msg = "FAISS module not available; cannot save index"
            raise RuntimeError(msg)

        index_candidate = self._require_index()
        module.write_index(index_candidate, index_uri)

    # Internal helpers -------------------------------------------------------

    def _require_index(self) -> FaissIndexProtocol:
        """Return the initialized FAISS index or raise.

        Returns
        -------
        FaissIndexProtocol
            Initialized FAISS index.

        Raises
        ------
        RuntimeError
            If index is not initialized or fails protocol validation.
        """
        index_candidate = self.index
        if index_candidate is None:
            msg = "FAISS index not initialized"
            raise RuntimeError(msg)

        if not _is_faiss_index(index_candidate):
            msg = "FAISS index failed protocol validation"
            raise RuntimeError(msg)

        return index_candidate

    def _cpu_search(self, query: FloatVector, k: int) -> list[tuple[str, float]]:
        """Search using CPU fallback (inner product).

        Parameters
        ----------
        query : FloatVector
            Query vector.
        k : int
            Number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            List of (doc_id, score) tuples sorted by score descending.
        """
        cpu_matrix = self._cpu_matrix
        idmap = self.idmap
        if cpu_matrix is None or idmap is None:  # pragma: no cover - defensive fallback
            return []

        matrix: FloatMatrix = cpu_matrix
        vector: FloatVector = query
        scores_buffer: FloatVector = np.empty(matrix.shape[0], dtype=np.float32)
        np.dot(matrix, vector, out=scores_buffer)
        scores: FloatVector = scores_buffer
        idmap_list: list[str] = idmap
        score_list = cast("list[float]", scores.tolist())
        limit = min(k, scores.size)
        if limit == 0:
            return []

        indices = topk_indices(scores, limit)
        index_list = cast("list[int]", indices.tolist())
        return [
            (idmap_list[idx], float(score_list[idx])) for idx in index_list if idx < len(idmap_list)
        ]

    def _resolve_metric(self, module: FaissModuleProtocol) -> int:
        """Resolve metric string to FAISS metric constant.

        Parameters
        ----------
        module : FaissModuleProtocol
            FAISS module instance.

        Returns
        -------
        int
            FAISS metric constant.

        Raises
        ------
        ValueError
            If metric is not recognized.
        """
        metric = self.metric.lower()
        if metric == "ip":
            return module.metric_inner_product
        if metric == "l2":
            return module.metric_l2
        msg = f"Unsupported FAISS metric: {self.metric}"
        raise ValueError(msg)

    def _load_dense_vectors(self) -> DenseVecs:
        """Load dense vectors from DuckDB or Parquet.

        Returns
        -------
        DenseVecs
            Dense vectors container.

        Raises
        ------
        VectorSearchError
            If vectors cannot be loaded.
        """
        candidate = Path(self.db_path)
        if candidate.is_dir() or candidate.suffix == ".parquet":
            return self._load_from_parquet(candidate)

        if not candidate.exists():
            msg = f"DuckDB registry not found: {candidate}"
            raise VectorSearchError(msg)

        duckdb_module = _duckdb_module()
        try:
            con = duckdb_module.connect(str(candidate))
        except duckdb_module.Error:
            return self._load_from_parquet(candidate)

        try:
            record = fetch_one(
                con,
                "SELECT parquet_root FROM dense_runs ORDER BY created_at DESC LIMIT 1",
            )
        except duckdb_module.Error as exc:  # pragma: no cover - defensive fallback
            msg = f"Failed to query dense_runs: {exc}"
            raise VectorSearchError(msg) from exc
        finally:
            con.close()

        if record is None:
            msg = "dense_runs table is empty"
            raise VectorSearchError(msg)

        root_candidate = record[0]
        if not isinstance(root_candidate, str):
            msg = "dense_runs table is empty or malformed"
            raise VectorSearchError(msg)

        return self._load_from_parquet(Path(root_candidate))

    @staticmethod
    def _load_from_parquet(source: Path) -> DenseVecs:
        """Load dense vectors from Parquet file.

        Parameters
        ----------
        source : Path
            Path to Parquet file or directory.

        Returns
        -------
        DenseVecs
            Dense vectors container.

        Raises
        ------
        VectorSearchError
            If Parquet file cannot be read or is empty.
        """
        resolved = source.resolve()
        if not resolved.exists():
            msg = f"Parquet source not found: {resolved}"
            raise VectorSearchError(msg)

        duckdb_module = _duckdb_module()
        con = duckdb_module.connect(database=":memory:")
        try:
            rows = fetch_all(
                con,
                "SELECT chunk_id, vector FROM read_parquet(?, union_by_name=true)",
                [str(resolved)],
            )
        except duckdb_module.Error as exc:
            msg = f"Failed to load vectors from {resolved}: {exc}"
            raise VectorSearchError(msg) from exc
        finally:
            con.close()

        if not rows:
            msg = f"No vectors discovered in {resolved}"
            raise VectorSearchError(msg)

        ids: list[str] = []
        vector_rows: list[FloatArray] = []
        for chunk_id_val, vector_val in rows:
            ids.append(_as_optional_str(chunk_id_val))
            vector_array = np.asarray(vector_val, dtype=np.float32)
            vector_rows.append(vector_array)

        matrix: FloatMatrix = np.vstack(vector_rows).astype(np.float32, copy=False)
        normalized = normalize_l2(matrix, axis=1)
        return DenseVecs(ids=ids, matrix=normalized)
