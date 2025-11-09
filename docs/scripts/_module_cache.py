"""Shared helpers for lazily importing documentation script modules.

The docs tooling exposes thin wrappers that import heavy implementation
modules lazily.  This module centralises the caching logic so each wrapper
can depend on a single, typed implementation without repeating cache
management boilerplate or leaking ``Any`` through ``functools.cache``.
"""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from types import ModuleType
else:  # pragma: no cover - runtime stand-in for typing-only alias
    ModuleType = type(import_module("types"))

__all__ = ["ModuleExportsCache"]


class ModuleExportsCache:
    """Cache for lazily imported modules and their exported names.

    This cache provides lazy loading of Python modules and their exported names,
    storing both the module object and its __all__ attribute (if present) for
    efficient repeated access. The cache is initialized with a module path and
    loads the module only when first accessed.

    Parameters
    ----------
    module_path : str
        Fully qualified module path to cache (e.g., "package.module").
    """

    __slots__ = ("_exports", "_module", "_module_path")

    def __init__(self, module_path: str) -> None:
        self._module_path = module_path
        self._module: ModuleType | None = None
        self._exports: tuple[str, ...] | None = None

    def load_module(self) -> ModuleType:
        """Import and cache the target module.

        Returns
        -------
        ModuleType
            Imported module.
        """
        module = self._module
        if module is None:
            module = import_module(self._module_path)
            self._module = module
        return module

    def export_names(self) -> tuple[str, ...]:
        """Return exported attribute names from the cached module.

        Returns
        -------
        tuple[str, ...]
            Tuple of exported attribute names.
        """
        exports = self._exports
        if exports is not None:
            return exports

        module = self.load_module()
        exports_obj: object | None = getattr(module, "__all__", None)
        if isinstance(exports_obj, Iterable) and not isinstance(
            exports_obj, (str, bytes)
        ):
            candidates = cast("Iterable[object]", exports_obj)
            exports = tuple(str(name) for name in candidates)
        else:
            exports = tuple(name for name in dir(module) if not name.startswith("_"))

        self._exports = exports
        return exports

    def reset(self) -> None:
        """Clear cached module and export state."""
        self._module = None
        self._exports = None
