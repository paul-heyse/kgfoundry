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
    NDArrayF32 = Any  # type: ignore[assignment]
    NDArrayI64 = Any  # type: ignore[assignment]
    NDArrayAny = Any  # type: ignore[assignment]

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

    Returns
    -------
    object
        Imported module or attribute returned by the shared gate helper.
    """
    return _base_gate_import(module_name, purpose, min_version=min_version)
