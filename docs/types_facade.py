"""Public facade re-exporting typed helpers for documentation tooling.

This module wraps the internal ``docs._types`` package so that other modules
can import the typed helpers without referencing private module names.  It is a
thin layer that re-exports the symbols required by ``docs/conf.py`` and other
documentation tooling.
"""

from __future__ import annotations

from importlib import import_module

_astroid_facade = import_module("docs._types.astroid_facade")
AstroidBuilderFactory = _astroid_facade.AstroidBuilderFactory
AstroidBuilderProtocol = _astroid_facade.AstroidBuilderProtocol
AstroidManagerFactory = _astroid_facade.AstroidManagerFactory
AstroidManagerProtocol = _astroid_facade.AstroidManagerProtocol
coerce_astroid_builder_factory = _astroid_facade.coerce_astroid_builder_factory
coerce_astroid_manager_factory = _astroid_facade.coerce_astroid_manager_factory
_autoapi_parser = import_module("docs._types.autoapi_parser")
AutoapiParserProtocol = _autoapi_parser.AutoapiParserProtocol
coerce_parser_class = _autoapi_parser.coerce_parser_class
del _astroid_facade, _autoapi_parser

__all__ = [
    "AstroidBuilderFactory",
    "AstroidBuilderProtocol",
    "AstroidManagerFactory",
    "AstroidManagerProtocol",
    "AutoapiParserProtocol",
    "coerce_astroid_builder_factory",
    "coerce_astroid_manager_factory",
    "coerce_parser_class",
]
