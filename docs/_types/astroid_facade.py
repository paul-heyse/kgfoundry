"""Typed helpers for loading Astroid manager and builder classes."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from types import ModuleType

__all__ = [
    "AstroidBuilderFactory",
    "AstroidBuilderProtocol",
    "AstroidManagerFactory",
    "AstroidManagerProtocol",
    "coerce_astroid_builder_factory",
    "coerce_astroid_manager_factory",
]

_MISSING = object()


@runtime_checkable
class AstroidManagerProtocol(Protocol):
    """Subset of :mod:`astroid.manager` consumed by the docs build."""

    def build_from_file(self, path: str) -> object:
        """Return the AST for ``path``."""


@runtime_checkable
class AstroidBuilderProtocol(Protocol):
    """Subset of :mod:`astroid.builder` consumed by the docs build.

    Parameters
    ----------
    manager : AstroidManagerProtocol | None, optional
        Optional Astroid manager instance for configuration.
    """

    def __init__(self, manager: AstroidManagerProtocol | None = None) -> None: ...

    def file_build(self, file_path: str, module_name: str) -> object:
        """Return an AST node representing ``module_name`` at ``file_path``."""


@runtime_checkable
class AstroidManagerFactory(Protocol):
    """Callable returning Astroid manager instances."""

    def __call__(self) -> AstroidManagerProtocol:
        """Return a new Astroid manager instance."""
        ...


@runtime_checkable
class AstroidBuilderFactory(Protocol):
    """Callable returning Astroid builder instances."""

    def __call__(
        self,
        manager: AstroidManagerProtocol | None = None,
    ) -> AstroidBuilderProtocol:
        """Return a new Astroid builder instance."""
        ...


def _coerce_class(module: ModuleType, attribute: str, kind: str) -> type[object]:
    candidate_obj = getattr(module, attribute, _MISSING)
    if candidate_obj is _MISSING or not inspect.isclass(candidate_obj):
        message = f"Module '{module.__name__}' attribute '{attribute}' is not a {kind} class"
        raise TypeError(message)
    return cast("type[object]", candidate_obj)


def coerce_astroid_manager_factory(module: ModuleType) -> AstroidManagerFactory:
    """Return a callable that constructs Astroid manager instances.

    Parameters
    ----------
    module : ModuleType
        Astroid module to extract the manager class from.

    Returns
    -------
    AstroidManagerFactory
        Callable factory returning Astroid manager instances.
    """
    manager_cls = _coerce_class(module, "AstroidManager", "AstroidManager")
    return cast("AstroidManagerFactory", manager_cls)


def coerce_astroid_builder_factory(module: ModuleType) -> AstroidBuilderFactory:
    """Return a callable that constructs Astroid builder instances.

    Parameters
    ----------
    module : ModuleType
        Astroid module to extract the builder class from.

    Returns
    -------
    AstroidBuilderFactory
        Callable factory returning Astroid builder instances.
    """
    builder_cls = _coerce_class(module, "AstroidBuilder", "AstroidBuilder")
    builder_callable = cast("AstroidBuilderFactory", builder_cls)

    def factory(
        manager: AstroidManagerProtocol | None = None,
    ) -> AstroidBuilderProtocol:
        if manager is not None:
            try:
                return builder_callable(manager)
            except TypeError:
                return builder_callable()
        return builder_callable()

    return cast("AstroidBuilderFactory", factory)
