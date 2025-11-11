"""Public wrapper for :mod:`docs._types.griffe`."""

from __future__ import annotations

from importlib import import_module

_griffe = import_module("docs._types.griffe")
GriffeFacade = _griffe.GriffeFacade
GriffeNode = _griffe.GriffeNode
LoaderFacade = _griffe.LoaderFacade
MemberIterator = _griffe.MemberIterator
build_facade = _griffe.build_facade
del _griffe

__all__: tuple[str, ...] = (
    "GriffeFacade",
    "GriffeNode",
    "LoaderFacade",
    "MemberIterator",
    "build_facade",
)
