"""Public wrapper for :mod:`docs._types.sphinx_optional`."""

from __future__ import annotations

from importlib import import_module

_sphinx_optional = import_module("docs._types.sphinx_optional")
AstroidManagerFacade = _sphinx_optional.AstroidManagerFacade
AutoapiParserFacade = _sphinx_optional.AutoapiParserFacade
MissingDependencyError = _sphinx_optional.MissingDependencyError
OptionalDependencies = _sphinx_optional.OptionalDependencies
load_optional_dependencies = _sphinx_optional.load_optional_dependencies
del _sphinx_optional

__all__: tuple[str, ...] = (
    "AstroidManagerFacade",
    "AutoapiParserFacade",
    "MissingDependencyError",
    "OptionalDependencies",
    "load_optional_dependencies",
)
