"""Canonical typing façade for kgfoundry.

This module provides safe access to type hints and protocols without forcing
runtime imports of heavy optional dependencies. All imports of third-party types
(numpy, FastAPI, FAISS) are guarded behind TYPE_CHECKING blocks, ensuring that
postponed annotations (PEP 563) eliminate eager evaluation.

## Design

- **Type aliases & protocols** are re-exported at module level for annotations
- **Runtime helpers** (`gate_import`, `safe_get_type`) provide deferred access
- **Backward compatibility**: legacy imports from private modules are shimmed
  with deprecation warnings and will be removed after Phase 1

## Usage

**In annotated functions (preferred):**

    from __future__ import annotations

    from typing import TYPE_CHECKING
    from kgfoundry_common.typing import NavMap, ProblemDetails

    if TYPE_CHECKING:
        import numpy as np

    def process_vectors(vectors: np.ndarray) -> NavMap[str, ProblemDetails]:
        ...

**When runtime access to heavy types is unavoidable:**

    from kgfoundry_common.typing import gate_import
    np = gate_import("numpy", "numpy array processing")
    arr = np.zeros((10,))

## Schema & Contracts

JSON Schema 2020-12 examples and validation helpers are exported here for
cross-package use; see `kgfoundry_common.jsonschema_utils` for validators.
"""

# [nav:section public-api]

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing.heavy_deps import EXTRAS_HINT, HEAVY_DEPS


class _Comparable(Protocol):
    """Protocol for objects that support comparison operators.

    This protocol defines the interface for objects that can be compared using
    standard comparison operators (<, <=, >, >=). Used internally for version
    parsing and comparison operations.
    """

    def __lt__(self, other: _Comparable, /) -> bool:
        """Protocol stub for ``self < other``."""
        _protocol_stub("__lt__", self, other)

    def __le__(self, other: _Comparable, /) -> bool:
        """Protocol stub for ``self <= other``."""
        _protocol_stub("__le__", self, other)

    def __gt__(self, other: _Comparable, /) -> bool:
        """Protocol stub for ``self > other``."""
        _protocol_stub("__gt__", self, other)

    def __ge__(self, other: _Comparable, /) -> bool:
        """Protocol stub for ``self >= other``."""
        _protocol_stub("__ge__", self, other)


ParseVersionFn = Callable[[str], _Comparable]

_PARSE_VERSION: ParseVersionFn | None
try:
    from packaging.version import parse as _parse_version
except ImportError:
    _PARSE_VERSION = None
else:
    _PARSE_VERSION = cast("ParseVersionFn", _parse_version)


def _protocol_stub(method: str, *args: object) -> NoReturn:
    """Raise ``NotImplementedError`` when a structural protocol leaks to runtime."""
    message = (
        f"Comparable protocol method '{method}' must be implemented by the returned object. "
        f"Received args={args!r}."
    )
    raise NotImplementedError(message)


# Unused imports removed; TYPE_CHECKING used only for module-level identity

# =============================================================================
# Core typing exports (always safe)
# =============================================================================

__all__ = [
    "HEAVY_DEPS",
    "TYPE_CHECKING",
    "JSONValue",
    "NavMap",
    "ProblemDetails",
    "SymbolID",
    "gate_import",
    "resolve_faiss",
    "resolve_fastapi",
    "resolve_numpy",
    "safe_get_type",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# =============================================================================
# Type aliases (used in TYPE_CHECKING blocks across the codebase)
# =============================================================================

type NavMap = dict[str, object]
"""Canonical type alias for navigation/catalog maps in documentation artifacts."""

type ProblemDetails = dict[str, object]
"""RFC 9457 Problem Details object (JSON Schema validates structure)."""

type JSONValue = bool | int | float | str | dict[str, object] | list[object] | None
"""Valid JSON value types."""

type SymbolID = str
"""Canonical symbol identifier (format: 'py:package.module.Class.method')."""


# =============================================================================
# Runtime helpers (deferred imports with error handling)
# =============================================================================


# [nav:anchor gate_import]
def gate_import(
    module_name: str,
    purpose: str,
    min_version: str | None = None,
) -> object:
    """Lazily import a heavy optional dependency, raising if unavailable.

    Use this when a module genuinely requires heavy dependencies at runtime,
    and TYPE_CHECKING guards are insufficient. The helper provides structured
    error messages and caches results.

    Parameters
    ----------
    module_name : str
        Fully qualified module name (e.g., "numpy", "fastapi.routing").
    purpose : str
        Human-readable description of why the import is needed (used in errors).
    min_version : str | None, optional
        Minimum required version (checked via __version__ attribute).

    Returns
    -------
    object
        The imported module.

    Raises
    ------
    ImportError
        If the module is not installed or version requirement is unmet.

    Examples
    --------
    >>> np = gate_import("numpy", "array manipulation")
    >>> arr = np.zeros((10,))
    """
    module_root = module_name.split(".", maxsplit=1)[0]
    resolved_min = min_version if min_version is not None else HEAVY_DEPS.get(module_root)
    hint = EXTRAS_HINT.get(module_root)

    # Attempt import
    try:
        module = __import__(module_name, fromlist=[""])
    except ImportError as exc:
        msg = f"Cannot proceed with {purpose}: '{module_name}' is not installed."
        if hint:
            if " or " in hint:
                options = " or ".join(
                    f"pip install codeintel-rev[{option.strip()}]" for option in hint.split(" or ")
                )
                msg = f"{msg} Install with: {options}"
            else:
                msg = f"{msg} Install with: pip install codeintel-rev[{hint}]"
        else:
            msg = f"{msg} Install via: pip install {module_root}"
        raise ImportError(msg) from exc

    # Check version if requested
    if resolved_min is not None and hasattr(module, "__version__"):
        installed: str = getattr(module, "__version__", "unknown")
        if not _version_gte(installed, resolved_min):
            msg = (
                f"Cannot proceed with {purpose}: '{module_name}' version "
                f"{installed} < {resolved_min} (required)."
            )
            if hint:
                if " or " in hint:
                    options = " or ".join(
                        f"pip install --upgrade codeintel-rev[{option.strip()}]"
                        for option in hint.split(" or ")
                    )
                    msg = f"{msg} Upgrade via: {options}"
                else:
                    msg = f"{msg} Upgrade via: pip install codeintel-rev[{hint}]"
            else:
                msg = f"{msg} Upgrade via: pip install --upgrade {module_root}"
            raise ImportError(msg)

    return module


# [nav:anchor safe_get_type]
def safe_get_type(
    module_name: str,
    type_name: str,
    default: object = None,
) -> object:
    """Retrieve a type from a module, returning None if unavailable.

    Use this in annotations when you want to be defensive about optional types.

    Parameters
    ----------
    module_name : str
        Module name (e.g., "numpy").
    type_name : str
        Type/class name within the module (e.g., "ndarray").
    default : object, optional
        Default return value if import fails (default: None).

    Returns
    -------
    object
        The type, or default if the module/type is not available.

    Examples
    --------
    >>> ndarray_type = safe_get_type("numpy", "ndarray")
    >>> if ndarray_type is not None:
    ...     pass  # Do something with the type
    """
    try:
        module = __import__(module_name, fromlist=[type_name])
        return getattr(module, type_name, default)
    except (ImportError, AttributeError):
        return default


# =============================================================================
# Backward compatibility shims (deprecated)
# =============================================================================


# [nav:anchor resolve_numpy]
def resolve_numpy() -> object:
    """Resolve and return the numpy module (deprecated).

    .. deprecated:: 0.1.0
        Use `gate_import("numpy", "array processing")` instead.

    Returns
    -------
    object
        The numpy module.

    Notes
    -----
    Propagates :class:`ImportError` when ``numpy`` is not installed.
    """
    warnings.warn(
        "resolve_numpy() is deprecated; use gate_import('numpy', ...) instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return gate_import("numpy", "numpy array processing")


# [nav:anchor resolve_fastapi]
def resolve_fastapi() -> object:
    """Resolve and return the fastapi module (deprecated).

    .. deprecated:: 0.1.0
        Use `gate_import("fastapi", "FastAPI application")` instead.

    Returns
    -------
    object
        The fastapi module.

    Notes
    -----
    Propagates :class:`ImportError` when ``fastapi`` is not installed.
    """
    warnings.warn(
        "resolve_fastapi() is deprecated; use gate_import('fastapi', ...) instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return gate_import("fastapi", "FastAPI application")


# [nav:anchor resolve_faiss]
def resolve_faiss() -> object:
    """Resolve and return the faiss module (deprecated).

    .. deprecated:: 0.1.0
        Use `gate_import("faiss", "vector similarity search")` instead.

    Returns
    -------
    object
        The faiss module.

    Notes
    -----
    Propagates :class:`ImportError` when ``faiss`` is not installed.
    """
    warnings.warn(
        "resolve_faiss() is deprecated; use gate_import('faiss', ...) instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return gate_import("faiss", "vector similarity search")


# =============================================================================
# Internal helpers
# =============================================================================


def _version_gte(installed: str, required: str) -> bool:
    """Check if installed version >= required version.

    Parameters
    ----------
    installed : str
        Installed version string.
    required : str
        Required version string.

    Returns
    -------
    bool
        True if installed version is >= required version.
    """
    if _PARSE_VERSION is None:
        return installed >= required
    installed_version = _PARSE_VERSION(installed)
    required_version = _PARSE_VERSION(required)
    return installed_version >= required_version
