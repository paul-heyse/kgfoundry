"""Data structures describing generated docstrings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True, frozen=True)
class ParameterDoc:
    """Representation of a single parameter section entry."""

    name: str
    annotation: str | None
    description: str
    optional: bool = False
    default: str | None = None
    display_name: str | None = None
    kind: str = "positional_or_keyword"


@dataclass(slots=True, frozen=True)
class ReturnDoc:
    """Description for a return or yield value."""

    annotation: str | None
    description: str
    kind: Literal["returns", "yields"] = "returns"


@dataclass(slots=True, frozen=True)
class RaiseDoc:
    """Exception raised by a callable."""

    exception: str
    description: str


@dataclass(slots=True, frozen=True)
class DocstringSchema:
    """Structured docstring template information."""

    summary: str
    extended: str | None = None
    parameters: list[ParameterDoc] = field(default_factory=list)
    returns: list[ReturnDoc] = field(default_factory=list)
    raises: list[RaiseDoc] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class DocstringEdit:
    """Mutation describing the new docstring for a symbol."""

    qname: str
    text: str


__all__ = [
    "DocstringEdit",
    "DocstringSchema",
    "ParameterDoc",
    "RaiseDoc",
    "ReturnDoc",
]
