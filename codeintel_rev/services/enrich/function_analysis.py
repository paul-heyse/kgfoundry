# SPDX-License-Identifier: MIT
"""Shared helpers for per-function CST analysis with GOID metadata."""

from __future__ import annotations

from dataclasses import dataclass

import libcst as cst
from libcst import metadata as cst_metadata
from libcst.metadata import CodeRange, PositionProvider

from codeintel_rev.ids.goid import GOID, EntityDescriptor, GoidKind, RepoSnapshot, compute_goid

FunctionNode = cst.FunctionDef


@dataclass(slots=True, frozen=True)
class ParameterCounts:
    """Lightweight summary of function parameters."""

    total: int
    positional: int
    keyword_only: int
    has_varargs: bool
    has_varkw: bool


@dataclass(slots=True, frozen=True)
class FunctionInfo:
    """Resolved GOID metadata and positional anchors for a function node."""

    node: FunctionNode
    qualname: str
    kind: GoidKind
    is_async: bool
    start_line: int
    end_line: int
    goid: GOID


def collect_parameters(node: FunctionNode) -> list[cst.Param]:
    """Return parameters for ``node`` including variadics.

    Returns
    -------
    list[cst.Param]
        Parameters from positional-only, positional, keyword-only, and variadic slots.
    """
    params = list(node.params.posonly_params) + list(node.params.params)
    params.extend(node.params.kwonly_params)
    star_arg = _extract_param(node.params.star_arg)
    if star_arg is not None:
        params.append(star_arg)
    star_kwarg = _extract_param(node.params.star_kwarg)
    if star_kwarg is not None:
        params.append(star_kwarg)
    return params


def count_parameters(node: FunctionNode) -> ParameterCounts:
    """Return parameter count summary for ``node``.

    Returns
    -------
    ParameterCounts
        Aggregate parameter counts grouped by position and variadic flags.
    """
    positional = len(node.params.posonly_params) + len(node.params.params)
    keyword_only = len(node.params.kwonly_params)
    has_varargs = _extract_param(node.params.star_arg) is not None
    has_varkw = _extract_param(node.params.star_kwarg) is not None
    total = positional + keyword_only + int(has_varargs) + int(has_varkw)
    return ParameterCounts(
        total=total,
        positional=positional,
        keyword_only=keyword_only,
        has_varargs=has_varargs,
        has_varkw=has_varkw,
    )


class BaseFunctionVisitor(cst.CSTVisitor):
    """Base visitor that resolves GOIDs and qualnames for functions."""

    METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)

    def __init__(self, *, snapshot: RepoSnapshot, rel_path: str) -> None:
        self._snapshot = snapshot
        self._rel_path = rel_path
        self._class_stack: list[str] = []
        self._function_stack: list[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:  # noqa: N802
        """Track nesting for class scopes."""
        self._class_stack.append(node.name.value)

    def leave_ClassDef(self, node: cst.ClassDef) -> None:  # noqa: N802
        """Pop class scope on exit."""
        self._class_stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:  # noqa: N802
        """Handle function definitions (sync or async)."""
        info = self._build_info(node=node, is_async=node.asynchronous is not None)
        self.process_function(info)
        self._function_stack.append(node.name.value)

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:  # noqa: N802
        """Pop function scope on exit."""
        self._function_stack.pop()

    def process_function(self, info: FunctionInfo) -> None:
        """Process a single ``FunctionInfo`` instance."""
        raise NotImplementedError

    def _build_info(self, *, node: FunctionNode, is_async: bool) -> FunctionInfo:
        position = self.get_metadata(PositionProvider, node, default=CodeRange((0, 0), (0, 0)))
        start_line = position.start.line
        end_line = position.end.line
        qual_parts = [*self._class_stack, *self._function_stack, node.name.value]
        qualname = ".".join(part for part in qual_parts if part)
        kind: GoidKind = "method" if self._class_stack else "function"
        descriptor = EntityDescriptor(
            language="python",
            kind=kind,
            rel_path=self._rel_path,
            qualname=qualname or node.name.value,
            start_line=start_line,
            end_line=end_line,
        )
        goid = compute_goid(self._snapshot, descriptor)
        return FunctionInfo(
            node=node,
            qualname=qualname,
            kind=kind,
            is_async=is_async,
            start_line=start_line,
            end_line=end_line,
            goid=goid,
        )


def _extract_param(candidate: object) -> cst.Param | None:
    if isinstance(candidate, cst.Param):
        return candidate
    param_attr = getattr(candidate, "param", None)
    if isinstance(param_attr, cst.Param):
        return param_attr
    return None


__all__ = [
    "BaseFunctionVisitor",
    "FunctionInfo",
    "FunctionNode",
    "ParameterCounts",
    "collect_parameters",
    "count_parameters",
]
