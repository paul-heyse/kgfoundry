"""Helpers for lazily importing heavy optional dependencies."""

from __future__ import annotations

from types import ModuleType

from codeintel_rev.runtime.imports import gate_import


class LazyModule:
    """Proxy object that imports a module only when accessed.

    Parameters
    ----------
    module_name : str
        Name of the module to import lazily (e.g., "numpy", "fastapi").
    purpose : str
        Human-readable description of why this module is needed, used in
        error messages if import fails.
    """

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
            self._module = gate_import(self._module_name, self._purpose)
        return self._module

    def __getattr__(self, name: str) -> object:
        """Return attribute from the proxied module.

        Parameters
        ----------
        name : str
            Attribute name to retrieve from the proxied module.

        Returns
        -------
        object
            Attribute value from the proxied module.
        """
        return getattr(self.module(), name)

    def __setattr__(self, name: str, value: object) -> None:
        """Allow monkeypatching proxied modules in tests."""
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(self.module(), name, value)
