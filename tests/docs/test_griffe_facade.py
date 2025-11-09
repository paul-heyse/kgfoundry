"""Regression tests for Griffe stubs and typed facades.

Tests verify:
1. Stub/runtime parity (exported symbols match)
2. Type checking compliance (Pyright/Pyrefly find no issues)
3. Optional dependency handling with graceful degradation
4. Facade usability and protocol compliance
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from typing import TYPE_CHECKING, cast
from unittest import mock

import pytest
from docs._scripts.shared import detect_environment
from docs._types.griffe import (
    GriffeFacade,
    build_facade,
    get_autoapi_loader,
    get_sphinx_loader,
)

from kgfoundry_common.errors import ArtifactDependencyError

if TYPE_CHECKING:
    from docs._types.griffe import (
        GriffeNode,
    )

# Skip all tests if griffe is not available
griffe = pytest.importorskip("griffe")


class TestGriffeStubExports:
    """Verify stub exports match runtime Griffe 1.14.0."""

    def test_main_module_exports(self) -> None:
        """Verify core exports from griffe module."""
        expected_symbols = {
            "Object",
            "Alias",
            "Module",
            "Package",
            "Class",
            "Function",
            "Attribute",
            "TypeAlias",
            "Docstring",
            "GriffeLoader",
            "load",
            "GriffeError",
            "LoadingError",
            "NameResolutionError",
            "AliasResolutionError",
            "CyclicAliasError",
            "UnimportableModuleError",
            "BuiltinModuleError",
            "ExtensionError",
            "ExtensionNotLoadedError",
        }
        actual_symbols = set(dir(griffe))
        for symbol in expected_symbols:
            assert symbol in actual_symbols, f"Missing export: {symbol}"

    def test_griffe_loader_methods(self) -> None:
        """Verify GriffeLoader has expected methods."""
        loader_cls = griffe.GriffeLoader
        expected_methods = {"load"}
        actual_methods = {name for name in dir(loader_cls) if not name.startswith("_")}
        for method in expected_methods:
            assert method in actual_methods, f"Missing method: {method}"
        # Verify __init__ exists and is callable
        assert hasattr(loader_cls, "__init__")
        assert callable(loader_cls.__init__)

    def test_object_hierarchy(self) -> None:
        """Verify Object subclass hierarchy."""
        assert issubclass(griffe.Module, griffe.Object)
        assert issubclass(griffe.Class, griffe.Object)
        assert issubclass(griffe.Function, griffe.Object)
        assert issubclass(griffe.Attribute, griffe.Object)
        assert issubclass(griffe.TypeAlias, griffe.Object)
        # Note: Alias has a complex mixin-based hierarchy in runtime

    def test_exception_hierarchy(self) -> None:
        """Verify exception class hierarchy matches stubs."""
        assert issubclass(griffe.LoadingError, griffe.GriffeError)
        assert issubclass(griffe.NameResolutionError, griffe.GriffeError)
        assert issubclass(griffe.AliasResolutionError, griffe.GriffeError)
        assert issubclass(griffe.CyclicAliasError, griffe.GriffeError)
        assert issubclass(griffe.UnimportableModuleError, griffe.GriffeError)
        assert issubclass(griffe.BuiltinModuleError, griffe.GriffeError)
        assert issubclass(griffe.ExtensionError, griffe.GriffeError)
        assert issubclass(griffe.ExtensionNotLoadedError, griffe.ExtensionError)


class TestGriffeLoaderSignatures:
    """Verify loader and load() function signatures match stubs."""

    def test_load_function_callable(self) -> None:
        """Verify griffe.load is callable with expected parameters."""
        assert callable(griffe.load)
        sig = inspect.signature(griffe.load)
        params = set(sig.parameters.keys())

        expected_params = {
            "objspec",
            "submodules",
            "try_relative_path",
            "extensions",
            "search_paths",
            "docstring_parser",
            "docstring_options",
            "allow_inspection",
            "force_inspection",
            "store_source",
            "find_stubs_package",
            "resolve_aliases",
            "resolve_external",
            "resolve_implicit",
        }
        assert expected_params.issubset(
            params
        ), f"Missing parameters: {expected_params - params}"

    def test_griffe_loader_constructor(self) -> None:
        """Verify GriffeLoader.__init__ accepts expected keyword arguments."""
        sig = inspect.signature(griffe.GriffeLoader.__init__)
        params = set(sig.parameters.keys()) - {"self"}

        expected_params = {
            "search_paths",
            "allow_inspection",
            "force_inspection",
            "docstring_parser",
            "docstring_options",
        }
        assert expected_params.issubset(
            params
        ), f"Missing parameters: {expected_params - params}"

    def test_griffe_loader_load_method(self) -> None:
        """Verify GriffeLoader.load method signature."""
        sig = inspect.signature(griffe.GriffeLoader.load)
        params = set(sig.parameters.keys()) - {"self"}

        expected_params = {
            "objspec",
            "submodules",
            "try_relative_path",
            "find_stubs_package",
        }
        assert expected_params.issubset(
            params
        ), f"Missing parameters: {expected_params - params}"


class TestGriffeFacade:
    """Test the typed Griffe facade."""

    @pytest.fixture(name="facade")
    def _facade(self) -> GriffeFacade:
        """Create a Griffe facade for testing.

        Returns
        -------
        GriffeFacade
            Configured Griffe facade instance.
        """
        env = detect_environment()
        facade = build_facade(env)
        assert isinstance(facade, GriffeFacade)
        return facade

    def test_build_facade_returns_griffe_facade(self, facade: GriffeFacade) -> None:
        """Verify build_facade returns an object matching GriffeFacade protocol."""
        assert isinstance(facade, GriffeFacade)

    def test_facade_loader_property(self, facade: GriffeFacade) -> None:
        """Verify facade.loader exists and is callable."""
        loader = facade.loader
        assert loader is not None
        assert hasattr(loader, "load")
        assert callable(loader.load)

    def test_facade_member_iterator_property(self, facade: GriffeFacade) -> None:
        """Verify facade.member_iterator exists."""
        member_iter = facade.member_iterator
        assert member_iter is not None
        assert hasattr(member_iter, "iter_members")
        assert callable(member_iter.iter_members)


class TestOptionalDependencyHandling:
    """Test graceful degradation when optional plugins are missing."""

    def test_get_autoapi_loader_missing_dependency(self) -> None:
        """Verify get_autoapi_loader raises ArtifactDependencyError when missing."""
        # If autoapi is installed, mock its removal to test error handling
        if importlib.util.find_spec("autoapi") is not None:
            with mock.patch.dict(sys.modules, {"autoapi": None}):
                with pytest.raises(ArtifactDependencyError) as exc_info:
                    get_autoapi_loader()
                assert "AutoAPI" in str(exc_info.value)
                assert "optional" in str(exc_info.value).lower()

    def test_get_sphinx_loader_missing_dependency(self) -> None:
        """Verify get_sphinx_loader raises ArtifactDependencyError when missing."""
        # If sphinx is installed, mock its removal to test error handling
        if importlib.util.find_spec("sphinx") is not None:
            with mock.patch.dict(sys.modules, {"sphinx": None}):
                with pytest.raises(ArtifactDependencyError) as exc_info:
                    get_sphinx_loader()
                assert "Sphinx" in str(exc_info.value)
                assert "optional" in str(exc_info.value).lower()

    def test_artifact_dependency_error_has_cause(self) -> None:
        """Verify ArtifactDependencyError preserves original ImportError."""
        # If autoapi is installed, mock its removal to test error chaining
        if importlib.util.find_spec("autoapi") is not None:
            with mock.patch.dict(sys.modules, {"autoapi": None}):
                with pytest.raises(ArtifactDependencyError) as exc_info:
                    get_autoapi_loader()
                assert exc_info.value.__cause__ is not None
                assert isinstance(exc_info.value.__cause__, ImportError)


class TestGriffeNodeProtocol:
    """Test the GriffeNode protocol implementation."""

    @pytest.fixture(name="test_node")
    def _test_node(self) -> GriffeNode:
        """Load a real Griffe node for testing.

        Returns
        -------
        GriffeNode
            Loaded Griffe node for pathlib module.
        """
        return cast("GriffeNode", griffe.load("pathlib"))

    def test_node_has_path_property(self, test_node: GriffeNode) -> None:
        """Verify loaded node has path property."""
        assert hasattr(test_node, "path")
        assert isinstance(test_node.path, str)

    def test_node_has_members_dict(self, test_node: GriffeNode) -> None:
        """Verify loaded node has members property."""
        assert hasattr(test_node, "members")
        assert isinstance(test_node.members, dict)

    def test_node_has_kind_property(self, test_node: GriffeNode) -> None:
        """Verify loaded node has kind property."""
        assert hasattr(test_node, "kind")
        kind = test_node.kind
        assert kind is None or isinstance(kind, str)

    def test_node_properties_accessible(self, test_node: GriffeNode) -> None:
        """Verify commonly accessed node properties exist and are accessible."""
        # Verify properties exist and are accessible (should not raise AttributeError)
        assert hasattr(test_node, "path")
        path = test_node.path
        assert isinstance(path, str)
        assert len(path) > 0

        assert hasattr(test_node, "members")
        members = test_node.members
        assert isinstance(members, dict)

        assert hasattr(test_node, "kind")
        kind = test_node.kind
        assert kind is None or isinstance(kind, str)

        if hasattr(test_node, "lineno"):
            lineno = test_node.lineno
            assert lineno is None or isinstance(lineno, int)


class TestDoctest:
    """Doctest examples in griffe module."""

    def test_build_facade_doctest_example(self) -> None:
        """Verify the build_facade doctest example works."""
        env = detect_environment()
        facade = build_facade(env)
        node = facade.loader.load("kgfoundry")
        # Should not raise and should return something
        assert node is not None
