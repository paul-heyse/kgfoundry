"""Typed facades for optional Sphinx dependencies.

This module provides protocols and loaders for optional Sphinx integrations
(Astroid, AutoAPI, docstring overrides). Guarded imports ensure graceful
degradation when dependencies are missing, with descriptive error messages.

Examples
--------
>>> from docs._types.sphinx_optional import load_optional_dependencies
>>> try:
...     deps = load_optional_dependencies()
... except ImportError as e:
...     print(f"Missing optional dependency: {e}")
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from docs._types.astroid_facade import AstroidManagerProtocol
    from docs._types.autoapi_parser import AutoapiParserProtocol, coerce_parser_class
else:  # pragma: no cover - runtime import guarded
    _astroid_facade = import_module("docs._types.astroid_facade")
    AstroidManagerProtocol = _astroid_facade.AstroidManagerProtocol
    _autoapi_parser = import_module("docs._types.autoapi_parser")
    AutoapiParserProtocol = _autoapi_parser.AutoapiParserProtocol
    coerce_parser_class = _autoapi_parser.coerce_parser_class
    del _astroid_facade, _autoapi_parser

__all__ = [
    "AstroidManagerFacade",
    "AutoapiParserFacade",
    "MissingDependencyError",
    "OptionalDependencies",
    "load_optional_dependencies",
]


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for docs building is missing.

    This exception is raised when code attempts to use optional Sphinx extensions
    (such as AutoAPI or Astroid) that are not installed. It provides a clear
    error message indicating which dependency is missing and why it's needed.

    Parameters
    ----------
    module_name : str
        Name of the missing module (e.g., "sphinx_autoapi").
    reason : str, optional
        Explanation of why the dependency is required.
        Defaults to empty string.

    Examples
    --------
    >>> raise MissingDependencyError("sphinx_autoapi", "required for API docs generation")
    """

    def __init__(self, module_name: str, reason: str = "") -> None:
        message = f"Missing optional dependency: {module_name}"
        if reason:
            message += f" ({reason})"
        super().__init__(message)
        self.module_name = module_name


type AutoapiParserFacade = type[AutoapiParserProtocol]


type AstroidManagerFacade = AstroidManagerProtocol


@runtime_checkable
class OptionalDependencies(Protocol):
    """Protocol aggregating optional dependency facades."""

    @property
    def autoapi_parser(self) -> AutoapiParserFacade:
        """Sphinx AutoAPI parser facade."""
        ...

    @property
    def astroid_manager(self) -> AstroidManagerFacade:
        """Astroid manager facade."""
        ...


class _OptionalDependenciesImpl:
    """Concrete implementation of OptionalDependencies.

    This class provides a concrete implementation of the OptionalDependencies
    protocol, aggregating optional dependency facades for AutoAPI and Astroid.
    It encapsulates the initialization and access to these optional components.

    Parameters
    ----------
    autoapi_parser : AutoapiParserFacade
        AutoAPI parser facade class for parsing API documentation.
    astroid_manager : AstroidManagerFacade
        Astroid manager facade for AST analysis and introspection.
    """

    def __init__(
        self,
        autoapi_parser: AutoapiParserFacade,
        astroid_manager: AstroidManagerFacade,
    ) -> None:
        self._autoapi_parser = autoapi_parser
        self._astroid_manager = astroid_manager

    @property
    def autoapi_parser(self) -> AutoapiParserFacade:
        """Return the AutoAPI parser."""
        return self._autoapi_parser

    @property
    def astroid_manager(self) -> AstroidManagerFacade:
        """Return the Astroid manager."""
        return self._astroid_manager


def load_optional_dependencies() -> OptionalDependencies:
    """Load optional Sphinx dependencies with guarded imports.

    This function attempts to import and initialize optional Sphinx dependencies
    (AutoAPI parser and Astroid manager). If any dependency is missing, it raises
    MissingDependencyError with a clear error message indicating which dependency
    failed and why it's needed.

    Returns
    -------
    OptionalDependencies
        Aggregate facade providing access to optional components.

    Raises
    ------
    MissingDependencyError
        If AutoAPI parser module or Astroid module cannot be imported.

    Examples
    --------
    >>> from docs._types.sphinx_optional import load_optional_dependencies
    >>> try:
    ...     deps = load_optional_dependencies()
    ...     parser = deps.autoapi_parser
    ... except MissingDependencyError as e:
    ...     print(f"Cannot load AutoAPI: {e}")
    """
    # Try to import the AutoAPI parser module
    autoapi_module_name = "autoapi._parser"
    autoapi_import_err_msg = "autoapi is required for AutoAPI docs generation"
    try:
        parser_module = import_module(autoapi_module_name)
    except ImportError as e:
        raise MissingDependencyError(autoapi_module_name, autoapi_import_err_msg) from e
    parser_cls = coerce_parser_class(parser_module)

    # Try to import astroid
    astroid_module_name = "astroid"
    astroid_import_err_msg = "astroid is required for AST analysis during docs build"
    try:
        astroid = import_module(astroid_module_name)
    except ImportError as e:
        raise MissingDependencyError(astroid_module_name, astroid_import_err_msg) from e

    # If we get here, both are available
    # Return facades wrapping the actual modules/objects
    manager_facade = cast("AstroidManagerFacade", astroid.MANAGER)
    return _OptionalDependenciesImpl(
        autoapi_parser=parser_cls,
        astroid_manager=manager_facade,
    )
