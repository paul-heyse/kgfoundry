"""Helpers for lazily importing heavy optional dependencies."""

from __future__ import annotations

from types import ModuleType
from typing import cast

from codeintel_rev.typing import gate_import


class LazyModule:
    """Proxy object that imports a module only when accessed."""

    __slots__ = ("_module", "_module_name", "_purpose")

    def __init__(self, module_name: str, purpose: str) -> None:
        self._module_name = module_name
        self._purpose = purpose
        self._module: ModuleType | None = None

    def module(self) -> ModuleType:
        """Return the concrete module, importing it on first access.

        Returns
        -------
        ModuleType
            Imported module referenced by this proxy.
        """
        if self._module is None:
            imported = gate_import(self._module_name, self._purpose)
            self._module = cast("ModuleType", imported)
        return self._module

    def __getattr__(self, name: str) -> object:
        return getattr(self.module(), name)

    def __setattr__(self, name: str, value: object) -> None:
        """Allow monkeypatching proxied modules in tests."""
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(self.module(), name, value)
