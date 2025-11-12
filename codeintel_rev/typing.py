"""Typing façade for codeintel_rev heavy optional dependencies.

This module centralizes numpy-style array aliases and exposes a wrapper around
``kgfoundry_common.typing.gate_import`` that is aware of the local heavy
dependency policy. Keeping aliases and dependency metadata in one place lets
lint/type tooling (PR-E) and runtime helpers share the same source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    "NDArrayAny",
    "NDArrayF32",
    "NDArrayI64",
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
