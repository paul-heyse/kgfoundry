"""Tests for the typed namespace registry and proxy helpers.

This module verifies that the NamespaceRegistry provides correct lazy loading, caching, and error
handling without relying on Any types.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, NoReturn, cast

import pytest

from tests.helpers import load_attribute

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, MutableMapping

    from kgfoundry._namespace_proxy import NamespaceRegistry

    NamespaceRegistryType = type[NamespaceRegistry]

# Load test dependencies at module level to avoid PLC0415 violations
# Use string literals in casts to avoid runtime import of Callable
# Type checker will validate these via TYPE_CHECKING imports above
NamespaceRegistry = cast(
    "NamespaceRegistryType",
    load_attribute("kgfoundry._namespace_proxy", "NamespaceRegistry"),
)
namespace_exports = cast(
    "Callable[[ModuleType], list[str]]",
    load_attribute("kgfoundry._namespace_proxy", "namespace_exports"),
)
namespace_attach = cast(
    "Callable[[ModuleType, MutableMapping[str, object], Iterable[str]], None]",
    load_attribute("kgfoundry._namespace_proxy", "namespace_attach"),
)
namespace_dir = cast(
    "Callable[[ModuleType, Iterable[str]], list[str]]",
    load_attribute("kgfoundry._namespace_proxy", "namespace_dir"),
)
namespace_getattr = cast(
    "Callable[[ModuleType, str], object]",
    load_attribute("kgfoundry._namespace_proxy", "namespace_getattr"),
)


def _set_module_attr(module: ModuleType, name: str, value: object) -> None:
    """Assign an attribute on a module while preserving static typing."""
    setattr(module, name, value)


class TestNamespaceRegistry:
    """Tests for the NamespaceRegistry class."""

    def test_register_and_resolve_single_symbol(self) -> None:
        """Test basic registration and resolution of a symbol."""
        registry = NamespaceRegistry()
        test_value = {"key": "value"}
        registry.register("test_symbol", lambda: test_value)

        resolved = registry.resolve("test_symbol")
        assert resolved is test_value

    def test_resolve_caches_result(self) -> None:
        """Test that resolved symbols are cached to avoid repeated loader invocations."""
        registry = NamespaceRegistry()
        call_count = 0

        def loader() -> object:
            """Load symbol with call counting.

            Returns
            -------
            object
                Symbol value with call count. Never returns None.
            """
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        registry.register("cached_symbol", loader)

        # First resolution
        result1 = registry.resolve("cached_symbol")
        assert result1 == "result_1"
        assert call_count == 1

        # Second resolution should use cache
        result2 = registry.resolve("cached_symbol")
        assert result2 is result1
        assert call_count == 1  # Loader not called again

    def test_register_duplicate_symbol_raises_error(self) -> None:
        """Test that registering the same symbol twice raises ValueError."""
        registry = NamespaceRegistry()
        registry.register("symbol", lambda: "value1")

        expected_msg = "already registered"
        with pytest.raises(ValueError, match=expected_msg):
            registry.register("symbol", lambda: "value2")

    def test_resolve_unregistered_symbol_raises_error(self) -> None:
        """Test that resolving an unregistered symbol raises KeyError."""
        registry = NamespaceRegistry()
        registry.register("existing", lambda: "value")

        with pytest.raises(KeyError, match="not registered"):
            registry.resolve("missing")

    def test_resolve_unregistered_lists_available_symbols(self) -> None:
        """Test that KeyError message lists available symbols."""
        registry = NamespaceRegistry()
        registry.register("symbol_a", lambda: "a")
        registry.register("symbol_b", lambda: "b")

        msg_pattern = r"Available:.*symbol_a.*symbol_b"
        with pytest.raises(KeyError, match=msg_pattern):
            registry.resolve("symbol_c")

    def test_list_symbols_returns_sorted_names(self) -> None:
        """Test that list_symbols returns symbols in sorted order."""
        registry = NamespaceRegistry()
        registry.register("zebra", lambda: "z")
        registry.register("apple", lambda: "a")
        registry.register("mango", lambda: "m")

        symbols = registry.list_symbols()
        assert symbols == ["apple", "mango", "zebra"]

    def test_list_symbols_empty_registry(self) -> None:
        """Test that list_symbols returns empty list for empty registry."""
        registry = NamespaceRegistry()
        assert registry.list_symbols() == []

    def test_resolve_with_exception_in_loader(self) -> None:
        """Test that exceptions in loaders propagate correctly."""
        registry = NamespaceRegistry()

        def failing_loader() -> NoReturn:
            """Raise ``RuntimeError`` to simulate a failing loader.

            Raises
            ------
            RuntimeError
                Always raised with message "Loader failed" to simulate loader failure.

            Notes
            -----
            This function never returns normally; it always raises :exc:`RuntimeError`.
            The return type annotation ``NoReturn`` indicates that this function never
            returns a value.
            """
            raise RuntimeError("Loader failed")

        registry.register("failing", failing_loader)

        with pytest.raises(RuntimeError, match="Loader failed"):
            registry.resolve("failing")

    def test_resolve_returns_various_types(self) -> None:
        """Test that resolve works with various object types."""
        registry = NamespaceRegistry()

        test_cases: dict[str, object] = {
            "str_value": "hello",
            "int_value": 42,
            "list_value": [1, 2, 3],
            "dict_value": {"a": 1, "b": 2},
            "none_value": None,
        }

        # Create factories with explicit types that return captured values
        def make_factory(val: object) -> Callable[[], object]:
            """Create a factory that properly type-narrows lambda captures.

            Parameters
            ----------
            val : object
                Value to capture and return.

            Returns
            -------
            Callable[[], object]
                Factory function returning val.
            """

            def _factory() -> object:
                return val

            return _factory

        for name, value in test_cases.items():
            registry.register(name, make_factory(value))

        for name, expected_value in test_cases.items():
            resolved = registry.resolve(name)
            assert resolved == expected_value

    def test_multiple_registries_independent(self) -> None:
        """Test that multiple registries maintain separate state."""
        registry1 = NamespaceRegistry()
        registry2 = NamespaceRegistry()

        registry1.register("symbol", lambda: "value1")
        registry2.register("symbol", lambda: "value2")

        assert registry1.resolve("symbol") == "value1"
        assert registry2.resolve("symbol") == "value2"


class TestNamespaceHelpers:
    """Tests for namespace helper functions."""

    def test_namespace_exports_with_all_attribute(self) -> None:
        """Test that namespace_exports respects __all__ when present."""
        module = ModuleType("test_module")
        all_exports: list[str] = ["public_func", "public_class"]

        def _public_func() -> None:
            return None

        _set_module_attr(module, "__all__", all_exports)
        _set_module_attr(module, "public_func", _public_func)
        _set_module_attr(module, "public_class", type("PublicClass", (), {}))
        _set_module_attr(module, "_private", "should_not_appear")

        exports = namespace_exports(module)
        assert set(exports) == {"public_func", "public_class"}

    def test_namespace_exports_without_all_attribute(self) -> None:
        """Test that namespace_exports filters by convention when __all__ missing."""
        module = ModuleType("test_module")
        _set_module_attr(module, "public_attr", "public")
        _set_module_attr(module, "_private_attr", "private")

        exports = namespace_exports(module)
        assert "public_attr" in exports
        assert "_private_attr" not in exports

    def test_namespace_attach_populates_target(self) -> None:
        """Test that namespace_attach correctly populates target mapping."""
        module = ModuleType("test_module")
        _set_module_attr(module, "attr1", "value1")
        _set_module_attr(module, "attr2", "value2")

        target: dict[str, object] = {}
        namespace_attach(module, target, ["attr1", "attr2"])

        assert target == {"attr1": "value1", "attr2": "value2"}

    def test_namespace_dir_combines_exports_and_module_attrs(self) -> None:
        """Test that namespace_dir combines exports with non-dunder module attrs."""
        module = ModuleType("test_module")
        _set_module_attr(module, "exported1", "export1")
        _set_module_attr(module, "extra_attr", "extra")
        _set_module_attr(module, "__dunder__", "ignored")

        dir_result = namespace_dir(module, ["exported1", "exported2"])
        assert "exported1" in dir_result
        assert "exported2" in dir_result
        assert "extra_attr" in dir_result
        assert "__dunder__" not in dir_result

    def test_namespace_getattr_returns_attribute(self) -> None:
        """Test that namespace_getattr correctly retrieves attributes."""
        module = ModuleType("test_module")
        _set_module_attr(module, "test_attr", "test_value")

        result = namespace_getattr(module, "test_attr")
        assert result == "test_value"
