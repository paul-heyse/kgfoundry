"""Tests for the typed namespace registry and proxy helpers.

This module verifies that the NamespaceRegistry provides correct lazy loading, caching, and error
handling without relying on Any types.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, NoReturn

import pytest

from kgfoundry.tooling_bridge import (
    NamespaceRegistry,
    namespace_attach,
    namespace_dir,
    namespace_exports,
    namespace_getattr,
)
from tests._helpers import assertions

if TYPE_CHECKING:
    from collections.abc import Callable


def _set_module_attr(module: ModuleType, name: str, value: object) -> None:
    """Assign an attribute on a module while preserving static typing."""
    setattr(module, name, value)


def test_register_and_resolve_single_symbol() -> None:
    """Test basic registration and resolution of a symbol."""
    registry = NamespaceRegistry()
    test_value = {"key": "value"}
    registry.register("test_symbol", lambda: test_value)

    resolved = registry.resolve("test_symbol")
    assertions.expect_true(resolved is test_value, reason="resolved should be same object")


def test_resolve_caches_result() -> None:
    """Test that resolved symbols are cached to avoid repeated loader invocations."""
    registry = NamespaceRegistry()
    call_count = 0

    def loader() -> object:
        """Track invocation count and return result.

        Returns
        -------
        object
            String result with incremented call count.
        """
        nonlocal call_count
        call_count += 1
        return f"result_{call_count}"

    registry.register("cached_symbol", loader)
    result1 = registry.resolve("cached_symbol")
    assertions.expect_equal(result1, "result_1")
    assertions.expect_equal(call_count, 1)

    result2 = registry.resolve("cached_symbol")
    assertions.expect_true(
        result2 is result1, reason="second resolution should return cached result"
    )
    assertions.expect_equal(call_count, 1, reason="loader should not be called again")


def test_register_duplicate_symbol_raises_error() -> None:
    """Test that registering the same symbol twice raises ValueError."""
    registry = NamespaceRegistry()
    registry.register("symbol", lambda: "value1")

    expected_msg = "already registered"
    with pytest.raises(ValueError, match=expected_msg):
        registry.register("symbol", lambda: "value2")


def test_resolve_unregistered_symbol_raises_error() -> None:
    """Test that resolving an unregistered symbol raises KeyError."""
    registry = NamespaceRegistry()
    registry.register("existing", lambda: "value")

    with pytest.raises(KeyError, match="not registered"):
        registry.resolve("missing")


def test_resolve_unregistered_lists_available_symbols() -> None:
    """Test that KeyError message lists available symbols."""
    registry = NamespaceRegistry()
    registry.register("symbol_a", lambda: "a")
    registry.register("symbol_b", lambda: "b")

    msg_pattern = r"Available:.*symbol_a.*symbol_b"
    with pytest.raises(KeyError, match=msg_pattern):
        registry.resolve("symbol_c")


def test_list_symbols_returns_sorted_names() -> None:
    """Test that list_symbols returns symbols in sorted order."""
    registry = NamespaceRegistry()
    registry.register("zebra", lambda: "z")
    registry.register("apple", lambda: "a")
    registry.register("mango", lambda: "m")

    symbols = registry.list_symbols()
    assertions.expect_sequence_equal(symbols, ["apple", "mango", "zebra"])


def test_list_symbols_empty_registry() -> None:
    """Test that list_symbols returns empty list for empty registry."""
    registry = NamespaceRegistry()
    assertions.expect_sequence_equal(registry.list_symbols(), [])


def test_resolve_with_exception_in_loader() -> None:
    """Test that exceptions in loaders propagate correctly."""
    registry = NamespaceRegistry()

    def failing_loader() -> NoReturn:
        """Raise RuntimeError to test error propagation.

        Raises
        ------
        RuntimeError
            Always raised with message "Loader failed" to test error propagation.
        """
        error_message = "Loader failed"
        raise RuntimeError(error_message)

    registry.register("failing", failing_loader)

    with pytest.raises(RuntimeError, match="Loader failed"):
        registry.resolve("failing")


def test_resolve_returns_various_types() -> None:
    """Test that resolve works with various object types."""
    registry = NamespaceRegistry()

    test_cases: dict[str, object] = {
        "str_value": "hello",
        "int_value": 42,
        "list_value": [1, 2, 3],
        "dict_value": {"a": 1, "b": 2},
        "none_value": None,
    }

    def make_factory(val: object) -> Callable[[], object]:
        """Create a factory function that returns a fixed value.

        Parameters
        ----------
        val : object
            Value to return from the factory function.

        Returns
        -------
        Callable[[], object]
            Factory function that returns the provided value.
        """

        def _factory() -> object:
            return val

        return _factory

    for name, value in test_cases.items():
        registry.register(name, make_factory(value))

    for name, expected_value in test_cases.items():
        resolved = registry.resolve(name)
        assertions.expect_equal(resolved, expected_value)


def test_multiple_registries_independent() -> None:
    """Test that multiple registries maintain separate state."""
    registry1 = NamespaceRegistry()
    registry2 = NamespaceRegistry()

    registry1.register("symbol", lambda: "value1")
    registry2.register("symbol", lambda: "value2")

    assertions.expect_equal(registry1.resolve("symbol"), "value1")
    assertions.expect_equal(registry2.resolve("symbol"), "value2")


def test_namespace_exports_with_all_attribute() -> None:
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
    assertions.expect_equal(set(exports), {"public_func", "public_class"})


def test_namespace_exports_without_all_attribute() -> None:
    """Test that namespace_exports filters by convention when __all__ missing."""
    module = ModuleType("test_module")
    _set_module_attr(module, "public_attr", "public")
    _set_module_attr(module, "_private_attr", "private")

    exports = namespace_exports(module)
    assertions.expect_in("public_attr", exports)
    assertions.expect_false(
        "_private_attr" in exports, reason="private attributes should not be exported"
    )


def test_namespace_attach_populates_target() -> None:
    """Test that namespace_attach correctly populates target mapping."""
    module = ModuleType("test_module")
    _set_module_attr(module, "attr1", "value1")
    _set_module_attr(module, "attr2", "value2")

    target: dict[str, object] = {}
    namespace_attach(module, target, ["attr1", "attr2"])

    assertions.expect_mapping_equal(target, {"attr1": "value1", "attr2": "value2"})


def test_namespace_dir_combines_exports_and_module_attrs() -> None:
    """Test that namespace_dir combines exports with non-dunder module attrs."""
    module = ModuleType("test_module")
    _set_module_attr(module, "exported1", "export1")
    _set_module_attr(module, "extra_attr", "extra")
    _set_module_attr(module, "__dunder__", "ignored")

    dir_result = namespace_dir(module, ["exported1", "exported2"])
    assertions.expect_in("exported1", dir_result)
    assertions.expect_in("exported2", dir_result)
    assertions.expect_in("extra_attr", dir_result)
    assertions.expect_false(
        "__dunder__" in dir_result, reason="dunder attributes should not appear"
    )


def test_namespace_getattr_returns_attribute() -> None:
    """Test that namespace_getattr correctly retrieves attributes."""
    module = ModuleType("test_module")
    _set_module_attr(module, "test_attr", "test_value")

    result = namespace_getattr(module, "test_attr")
    assertions.expect_equal(result, "test_value")
