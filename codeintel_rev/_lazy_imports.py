"""Helpers for lazily importing heavy optional dependencies."""

from __future__ import annotations

from types import ModuleType
from typing import Any, cast

from codeintel_rev.typing import gate_import


class LazyModule:
    """Proxy object that imports a module only when accessed."""

    __slots__ = ("_module_name", "_purpose", "_module")

    def __init__(self, module_name: str, purpose: str) -> None:
        self._module_name = module_name
        self._purpose = purpose
        self._module: ModuleType | None = None

    def module(self) -> ModuleType:
        """Return the concrete module, importing it on first access."""
        if self._module is None:
            imported = gate_import(self._module_name, self._purpose)
            self._module = cast("ModuleType", imported)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self.module(), name)
