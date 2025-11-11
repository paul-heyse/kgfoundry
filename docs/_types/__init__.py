"""Internal typed models for documentation artifacts.

This private package exports authoritative models for documentation artifact
pipelines. Models are built on Pydantic V2 BaseModel for full type safety,
self-documenting schemas, and built-in validation.

Sub-modules:

- **artifacts**: Authoritative Pydantic models for symbol index, delta, and
  reverse-lookup artifacts. These models are frozen (immutable) and include
  field validators for defensive validation.
- **griffe**: Runtime-checkable protocols and typed facade for Griffe
  integration (optional dependency).
- **sphinx_optional**: Typed facades for optional Sphinx/Astroid dependencies
  with graceful handling of missing imports.
"""

from __future__ import annotations

from importlib import import_module

artifacts = import_module("docs._types.artifacts")
griffe = import_module("docs._types.griffe")
sphinx_optional = import_module("docs._types.sphinx_optional")
_astroid_facade = import_module("docs._types.astroid_facade")

ArtifactValidationError = artifacts.ArtifactValidationError
JsonPayload = artifacts.JsonPayload
JsonPrimitive = artifacts.JsonPrimitive
JsonValue = artifacts.JsonValue
LineSpan = artifacts.LineSpan
SymbolDeltaChange = artifacts.SymbolDeltaChange
SymbolDeltaPayload = artifacts.SymbolDeltaPayload
SymbolIndexArtifacts = artifacts.SymbolIndexArtifacts
SymbolIndexRow = artifacts.SymbolIndexRow
dump_symbol_delta = artifacts.dump_symbol_delta
dump_symbol_index = artifacts.dump_symbol_index
load_symbol_delta = artifacts.load_symbol_delta
load_symbol_index = artifacts.load_symbol_index
symbol_delta_from_json = artifacts.symbol_delta_from_json
symbol_delta_to_payload = artifacts.symbol_delta_to_payload
symbol_index_from_json = artifacts.symbol_index_from_json
symbol_index_to_payload = artifacts.symbol_index_to_payload

AstroidBuilderFactory = _astroid_facade.AstroidBuilderFactory
AstroidBuilderProtocol = _astroid_facade.AstroidBuilderProtocol
AstroidManagerFactory = _astroid_facade.AstroidManagerFactory
AstroidManagerProtocol = _astroid_facade.AstroidManagerProtocol
coerce_astroid_builder_factory = _astroid_facade.coerce_astroid_builder_factory
coerce_astroid_manager_factory = _astroid_facade.coerce_astroid_manager_factory

GriffeFacade = griffe.GriffeFacade
GriffeNode = griffe.GriffeNode
LoaderFacade = griffe.LoaderFacade
MemberIterator = griffe.MemberIterator
build_facade = griffe.build_facade

AstroidManagerFacade = sphinx_optional.AstroidManagerFacade
AutoapiParserFacade = sphinx_optional.AutoapiParserFacade
MissingDependencyError = sphinx_optional.MissingDependencyError
OptionalDependencies = sphinx_optional.OptionalDependencies
load_optional_dependencies = sphinx_optional.load_optional_dependencies

del _astroid_facade

__all__ = [
    "ArtifactValidationError",
    "AstroidBuilderFactory",
    "AstroidBuilderProtocol",
    "AstroidManagerFacade",
    "AstroidManagerFactory",
    "AstroidManagerProtocol",
    "AutoapiParserFacade",
    "GriffeFacade",
    "GriffeNode",
    "JsonPayload",
    "JsonPrimitive",
    "JsonValue",
    "LineSpan",
    "LoaderFacade",
    "MemberIterator",
    "MissingDependencyError",
    "OptionalDependencies",
    "SymbolDeltaChange",
    "SymbolDeltaPayload",
    "SymbolIndexArtifacts",
    "SymbolIndexRow",
    "build_facade",
    "coerce_astroid_builder_factory",
    "coerce_astroid_manager_factory",
    "dump_symbol_delta",
    "dump_symbol_index",
    "load_optional_dependencies",
    "load_symbol_delta",
    "load_symbol_index",
    "symbol_delta_from_json",
    "symbol_delta_to_payload",
    "symbol_index_from_json",
    "symbol_index_to_payload",
]
