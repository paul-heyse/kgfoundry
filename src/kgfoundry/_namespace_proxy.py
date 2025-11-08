"""Internal helpers for namespace bridge modules.

This module is an implementation detail. Downstream code should import
``kgfoundry.tooling_bridge`` instead of relying on these helpers directly.

The NamespaceRegistry provides a typed, lazy-loading mechanism for resolving
module exports without relying on dynamic Any types. Symbols are explicitly
registered with type-aware loaders, enabling full type-checking support.
"""
# [nav:section public-api]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar, cast

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, MutableMapping
    from types import ModuleType

# Type variable for generic loader results
T = TypeVar("T")


@dataclass(slots=True, frozen=True)
# [nav:anchor NamespaceRegistry]
class NamespaceRegistry:
    """Typed registry for lazy-loading module symbols.

    This registry encapsulates symbol metadata (name, loader callable) and provides typed methods to
    register and resolve symbols without relying on Any types. Loaders are cached to avoid repeated
    module imports.
    """

    _registry: dict[str, Callable[[], object]] = field(default_factory=dict, init=False)
    _cache: dict[str, object] = field(default_factory=dict, init=False)

    def register(self, name: str, loader: Callable[[], T]) -> None:
        """Register a symbol with a lazy loader.

        Parameters
        ----------
        name : str
            The symbol name to register.
        loader : Callable[[], T]
            A callable that returns the symbol when invoked.

        Raises
        ------
        ValueError
            If the symbol is already registered.
        """
        if name in self._registry:
            message = f"Symbol {name!r} is already registered"
            raise ValueError(message)
        self._registry[name] = loader

    def resolve(self, name: str) -> object:
        """Resolve a symbol by invoking its loader.

        Parameters
        ----------
        name : str
            The symbol name to resolve.

        Returns
        -------
        object
            The loaded symbol.

        Raises
        ------
        KeyError
            If the symbol is not registered.
        """
        if name not in self._registry:
            available = sorted(self._registry.keys())
            message = f"Symbol {name!r} not registered. Available: {available}"
            raise KeyError(message)

        # Return cached result if available
        if name in self._cache:
            return self._cache[name]

        # Invoke loader and cache result
        result = self._registry[name]()
        self._cache[name] = result
        return result

    def list_symbols(self) -> list[str]:
        """List all registered symbol names.

        Returns
        -------
        list[str]
            Sorted list of registered symbols.
        """
        return sorted(self._registry.keys())


# [nav:anchor namespace_getattr]
def namespace_getattr(module: ModuleType, name: str) -> object:
    """Return ``name`` from ``module`` while preserving the original attribute.

    Parameters
    ----------
    module : ModuleType
        Module to get attribute from.
    name : str
        Attribute name to get.

    Returns
    -------
    object
        Attribute value.
    """
    # getattr returns Any; cast to object for type safety
    return cast("object", getattr(module, name))


# [nav:anchor namespace_exports]
def namespace_exports(module: ModuleType) -> list[str]:
    """Return the public export list for ``module`` respecting ``__all__``.

    Parameters
    ----------
    module : ModuleType
        Module to get exports from.

    Returns
    -------
    list[str]
        List of public export names.
    """
    exports: object = getattr(module, "__all__", None)
    if isinstance(exports, (list, tuple, set)):
        # Cast narrowed iterable to ensure static type checkers can infer str() return
        return [str(item) for item in cast("Iterable[object]", exports)]
    return [attr for attr in dir(module) if not attr.startswith("_")]


# [nav:anchor namespace_attach]
def namespace_attach(
    module: ModuleType,
    target: MutableMapping[str, object],
    names: Iterable[str],
) -> None:
    """Populate ``target`` with attributes sourced from ``module``."""
    for name in names:
        # getattr returns Any; cast to object for type safety
        target[name] = cast("object", getattr(module, name))


# [nav:anchor namespace_dir]
def namespace_dir(module: ModuleType, exports: Iterable[str]) -> list[str]:
    """Return the combined attribute listing exposed by a namespace bridge.

    Parameters
    ----------
    module : ModuleType
        Module to get attributes from.
    exports : Iterable[str]
        Pre-defined export names.

    Returns
    -------
    list[str]
        Sorted list of combined attribute names.
    """
    exported = set(exports)
    exported.update(attr for attr in dir(module) if not attr.startswith("__"))
    return sorted(exported)


__all__ = [
    "NamespaceRegistry",
    "namespace_attach",
    "namespace_dir",
    "namespace_exports",
    "namespace_getattr",
]

__navmap__ = load_nav_metadata(__name__, tuple(__all__))
