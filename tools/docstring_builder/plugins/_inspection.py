"""Typed introspection module for plugin factory validation.

This module provides a typed wrapper around Python's inspect module to eliminate the 'Any' types
that come from its type stubs.
"""

from __future__ import annotations

import inspect as stdlib_inspect
from dataclasses import dataclass
from typing import Protocol

from tools.docstring_builder.parameters import ParameterKind, normalize_parameter_kind

__all__ = [
    "InspectableCallable",
    "ParameterInfo",
    "get_signature",
    "has_required_parameters",
]


class InspectableCallable(Protocol):
    """Callable protocol that avoids propagating ``Any`` types."""

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Invoke the callable."""


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    """Type-safe parameter information without Any types."""

    name: str
    """Name of the parameter."""

    has_default: bool
    """True if parameter has a default value."""

    is_var_positional: bool
    """True if parameter accepts *args."""

    is_var_keyword: bool
    """True if parameter accepts **kwargs."""


def get_signature(func: InspectableCallable) -> list[ParameterInfo]:
    """Get typed parameter information without Any types.

    Parameters
    ----------
    func : InspectableCallable
        The function or class to inspect.

    Returns
    -------
    list[ParameterInfo]
        List of parameter information objects.

    Raises
    ------
    ValueError
        If signature cannot be obtained.
    """
    try:
        sig = stdlib_inspect.signature(func)
    except (ValueError, TypeError) as exc:
        message = f"Could not inspect signature for {func}"
        raise ValueError(message) from exc

    params: list[ParameterInfo] = []

    for param_name, param in sig.parameters.items():
        # Get attributes without accessing Any-typed values directly
        empty_value: object = getattr(param, "empty", object())
        default_value: object = getattr(param, "default", empty_value)
        has_default = default_value is not empty_value
        kind_attr: object | None = getattr(param, "kind", None)
        kind = normalize_parameter_kind(kind_attr)
        is_var_pos = kind is ParameterKind.VAR_POSITIONAL
        is_var_kw = kind is ParameterKind.VAR_KEYWORD

        params.append(
            ParameterInfo(
                name=param_name,
                has_default=bool(has_default),
                is_var_positional=bool(is_var_pos),
                is_var_keyword=bool(is_var_kw),
            )
        )

    return params


def has_required_parameters(func: InspectableCallable) -> bool:
    """Check if a callable has required (non-default, non-*args/**kwargs) parameters.

    Parameters
    ----------
    func : InspectableCallable
        The function or class to check.

    Returns
    -------
    bool
        True if the callable has required parameters.
    """
    params = get_signature(func)

    for param in params:
        # Skip 'self' parameter for methods
        if param.name == "self":
            continue

        # Check if this parameter is required
        is_required = (
            not param.has_default and not param.is_var_positional and not param.is_var_keyword
        )

        if is_required:
            return True

    return False
