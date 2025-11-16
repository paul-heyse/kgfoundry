"""Public facade for reusable tooling helpers.

This package surfaces the modules within ``tools._shared`` under a stable
``tools.shared`` namespace so first-party code and external consumers can avoid
private imports that trigger lint violations.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING, Final

_SUBMODULES: Final[dict[str, str]] = {
    "cli": "tools._shared.cli",
    "logging": "tools._shared.logging",
    "metrics": "tools._shared.metrics",
    "problem_details": "tools._shared.problem_details",
    "proc": "tools._shared.proc",
    "schema": "tools._shared.schema",
    "settings": "tools._shared.settings",
    "validation": "tools._shared.validation",
}

__all__: tuple[str, ...] = (
    "cli",
    "logging",
    "metrics",
    "problem_details",
    "proc",
    "schema",
    "settings",
    "validation",
)


if TYPE_CHECKING:
    from types import ModuleType

    from tools._shared import (
        cli,
        logging,
        metrics,
        problem_details,
        proc,
        schema,
        settings,
        validation,
    )


def _load_submodule(name: str) -> ModuleType:
    module = import_module(_SUBMODULES[name])
    sys.modules.setdefault(f"{__name__}.{name}", module)
    return module


def __getattr__(name: str) -> ModuleType:
    """Get module attribute via lazy import.

    Parameters
    ----------
    name : str
        Module name to import.

    Returns
    -------
    ModuleType
        Imported module.

    Raises
    ------
    AttributeError
        If the module name is not in _SUBMODULES.
    """
    if name in _SUBMODULES:
        return _load_submodule(name)
    message = f"module '{__name__}' has no attribute '{name}'"
    raise AttributeError(message)


def __dir__() -> list[str]:
    """Return list of available module attributes.

    Returns
    -------
    list[str]
        Sorted list of attribute names including lazy imports.
    """
    namespace: dict[str, object] = globals()
    namespace_keys: set[str] = set(namespace.keys())
    return sorted({*namespace_keys, *__all__})
