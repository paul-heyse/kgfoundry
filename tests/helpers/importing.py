"""Utilities for deterministic module and attribute loading in tests.

These helpers wrap :mod:`importlib` to avoid inline ``import`` statements in
tests, satisfying Ruff's typing-gate checks while keeping imports explicit and
fully typed. They only perform runtime imports when invoked, which preserves
the lazy-loading guarantees required by the façade modules documented in
``AGENTS.md``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from types import ModuleType

T = TypeVar("T")


def load_module(module_name: str) -> ModuleType:
    """Import and return the module identified by ``module_name``.

    Parameters
    ----------
    module_name : str
        Dotted name of the module to import.

    Returns
    -------
    ModuleType
        Imported module object.
    """
    return import_module(module_name)


def load_attribute(module_name: str, attribute: str) -> object:
    """Load ``attribute`` from ``module_name`` and return the value.

    Parameters
    ----------
    module_name : str
        Dotted name of the module.
    attribute : str
        Attribute name to load.

    Returns
    -------
    object
        Attribute value.
    """
    module = load_module(module_name)
    attr: object = getattr(module, attribute)
    return attr


def load_typed_attribute[T](
    module_name: str, attribute: str, expected_type: type[T]
) -> T:
    """Load attribute and ensure it matches expected_type at runtime.

    Parameters
    ----------
    module_name : str
        Dotted name of the module.
    attribute : str
        Attribute name to load.
    expected_type : type[T]
        Expected type (checked at runtime).

    Returns
    -------
    T
        Attribute value typed as T.

    Raises
    ------
    TypeError
        If attribute does not match expected_type.
    """
    value = load_attribute(module_name, attribute)
    if isinstance(value, expected_type):
        return value

    message = f"{module_name}.{attribute} expected {expected_type!r} but received {type(value)!r}"
    raise TypeError(message)
