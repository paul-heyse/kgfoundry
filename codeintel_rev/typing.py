"""Typing façade for codeintel_rev heavy optional dependencies.

This module centralizes numpy-style array aliases and exposes a wrapper around
``kgfoundry_common.typing.gate_import`` that is aware of the local heavy
dependency policy. Keeping aliases and dependency metadata in one place lets
lint/type tooling (PR-E) and runtime helpers share the same source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

from kgfoundry_common.typing import gate_import as _base_gate_import

if TYPE_CHECKING:
    import numpy as _np
    import numpy.typing as _npt
else:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _npt = None  # type: ignore[assignment]

NDArrayF32: TypeAlias = "_npt.NDArray[_np.float32]"
NDArrayI64: TypeAlias = "_npt.NDArray[_np.int64]"
NDArrayAny: TypeAlias = "_npt.NDArray[Any]"

__all__ = [
    "NDArrayF32",
    "NDArrayI64",
    "NDArrayAny",
    "gate_import",
    "HEAVY_DEPS",
]


HEAVY_DEPS: dict[str, str | None] = {
    "numpy": "1.26",
    "faiss": None,
    "duckdb": None,
    "torch": None,
    "httpx": None,
    "onnxruntime": None,
    "lucene": None,
}
"""Registry of heavy optional dependencies and their minimum supported versions."""


def gate_import(
    module_name: str,
    purpose: str,
    *,
    min_version: str | None = None,
) -> object:
    """Resolve ``module_name`` lazily using the heavy dependency policy."""
    root = module_name.split(".", maxsplit=1)[0]
    resolved_min = min_version if min_version is not None else HEAVY_DEPS.get(root)
    return _base_gate_import(module_name, purpose, min_version=resolved_min)
