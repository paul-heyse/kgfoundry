"""Public wrapper for :mod:`docs._types.griffe`."""

from __future__ import annotations

from docs._types import griffe as _griffe

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
