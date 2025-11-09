"""Typed helpers for working with the AutoAPI parser module."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

__all__ = ["AutoapiParserProtocol", "coerce_parser_class"]

_MISSING = object()


def _protocol_stub(method: str, *args: object) -> NoReturn:
    """Raise ``NotImplementedError`` when a protocol stub executes at runtime."""
    arg_preview = ", ".join(repr(arg) for arg in args)
    message = (
        "AutoAPI parser implementations must override '{method}'. Received arguments: {args}."
    ).format(method=method, args=f"({arg_preview})" if arg_preview else "()")
    raise NotImplementedError(message)


class AutoapiParserProtocol(Protocol):
    """Subset of the AutoAPI parser surface used in the docs build."""

    def parse(self, node: object, /) -> object:
        """Return an AutoAPI document tree for ``node``."""
        _protocol_stub("parse", self, node)

    def _parse_file(
        self, file_path: str, condition: Callable[[str], bool], /
    ) -> object:
        """Parse ``file_path`` when ``condition`` evaluates to ``True``."""
        _protocol_stub("_parse_file", self, file_path, condition)

    def parse_file(self, file_path: str, /) -> object:
        """Wrap :meth:`_parse_file` for convenience."""
        _protocol_stub("parse_file", self, file_path)

    def parse_file_in_namespace(self, file_path: str, dir_root: str, /) -> object:
        """Parse ``file_path`` relative to ``dir_root`` namespace."""
        _protocol_stub("parse_file_in_namespace", self, file_path, dir_root)


def coerce_parser_class(
    module: ModuleType,
    attribute: str = "Parser",
) -> type[AutoapiParserProtocol]:
    """Return the ``Parser`` class from ``module`` with precise typing.

    Parameters
    ----------
    module : ModuleType
        AutoAPI parser module to extract the Parser class from.
    attribute : str, optional
        Attribute name to look for (defaults to "Parser").

    Returns
    -------
    type[AutoapiParserProtocol]
        Typed parser class.

    Raises
    ------
    TypeError
        If the module does not have the specified class attribute.
    """
    candidate_obj = getattr(module, attribute, _MISSING)
    if candidate_obj is _MISSING or not inspect.isclass(candidate_obj):
        message = f"Module '{module.__name__}' attribute '{attribute}' is not a class"
        raise TypeError(message)
    return cast("type[AutoapiParserProtocol]", candidate_obj)
