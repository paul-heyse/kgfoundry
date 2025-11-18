"""Runtime helpers for optional imports."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Final

HEAVY_DEPS: Final[frozenset[str]] = frozenset(
    {
        "duckdb",
        "faiss",
        "numpy",
        "pandas",
        "pyarrow",
        "torch",
        "transformers",
        "yaml",
    }
)


def gate_import(module_name: str, purpose: str | None = None) -> ModuleType:
    """Import ``module_name`` lazily and provide a descriptive error if missing.

    Parameters
    ----------
    module_name : str
        Name of the module to import.
    purpose : str | None, optional
        Optional human-readable description for error messaging.

    Returns
    -------
    ModuleType
        Imported module object.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover
        hint = f" (needed for {purpose})" if purpose else ""
        message = f"Missing optional dependency {module_name!r}{hint}"
        raise ImportError(message) from exc
