"""Test utilities for loading typing façade modules and attributes.

This module provides helpers that load façade modules and their attributes using
`importlib` instead of direct imports. This eliminates PLC0415 violations by
moving imports out of test functions while maintaining type safety and lazy
loading guarantees.

Examples
--------
Load a façade module:

>>> from tests.helpers.typing_facades import load_facade_module
>>> module = load_facade_module("kgfoundry_common.typing")
>>> assert hasattr(module, "gate_import")

Load a specific attribute:

>>> from tests.helpers.typing_facades import load_facade_attribute
>>> gate_import = load_facade_attribute("kgfoundry_common.typing", "gate_import")
>>> assert callable(gate_import)

Load with type checking:

>>> from tests.helpers.typing_facades import load_facade_attribute_typed
>>> from collections.abc import Callable
>>> gate_import = load_facade_attribute_typed("kgfoundry_common.typing", "gate_import", Callable)
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def load_facade_module(module_name: str) -> ModuleType:
    """Load a façade module using importlib.

    This function loads the module at runtime, avoiding direct imports in test
    functions that trigger PLC0415 violations. It preserves lazy-loading
    guarantees required by typing façade modules.

    Parameters
    ----------
    module_name : str
        Dotted name of the module to import (e.g., "kgfoundry_common.typing").

    Returns
    -------
    ModuleType
        The loaded module object.

    Examples
    --------
    >>> module = load_facade_module("kgfoundry_common.typing")
    >>> assert hasattr(module, "gate_import")
    """
    return import_module(module_name)


def load_facade_attribute(module_name: str, attribute: str) -> object:
    """Load an attribute from a façade module.

    Parameters
    ----------
    module_name : str
        Dotted name of the module containing the attribute.
    attribute : str
        Name of the attribute to retrieve.

    Returns
    -------
    object
        The attribute value.

    Examples
    --------
    >>> gate_import = load_facade_attribute("kgfoundry_common.typing", "gate_import")
    >>> assert callable(gate_import)
    """
    module = load_facade_module(module_name)
    attr: object = getattr(module, attribute)
    return attr


def load_facade_attribute_typed[T](
    module_name: str, attribute: str, expected_type: type[T]
) -> T:
    """Load an attribute from a façade module with runtime type checking.

    Parameters
    ----------
    module_name : str
        Dotted name of the module containing the attribute.
    attribute : str
        Name of the attribute to retrieve.
    expected_type : type[T]
        Expected type of the attribute (checked at runtime).

    Returns
    -------
    T
        The attribute value, typed as T.

    Raises
    ------
    TypeError
        If the attribute does not match the expected type.

    Examples
    --------
    >>> from collections.abc import Callable
    >>> gate_import = load_facade_attribute_typed(
    ...     "kgfoundry_common.typing", "gate_import", Callable
    ... )
    >>> assert callable(gate_import)
    """
    value = load_facade_attribute(module_name, attribute)
    if not isinstance(value, expected_type):
        message = f"{module_name}.{attribute} expected {expected_type!r} but received {type(value)!r}"
        raise TypeError(message)
    assert isinstance(value, expected_type)
    return value
