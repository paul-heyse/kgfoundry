"""Common mixins for bridging LibCST CamelCase hooks to snake_case overrides."""

from __future__ import annotations

import libcst as cst


class ImportFromTransformerMixin:
    """Provide a snake_case hook for ``leave_ImportFrom``."""

    # ruff: noqa: N802 - LibCST requires CamelCase hook names
    def leave_ImportFrom(
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]:
        return self.leave_import_from(original_node, updated_node)

    def leave_import_from(
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]:
        """Snake_case override called by LibCST when exiting ImportFrom nodes."""
        del original_node
        return updated_node


class CallTransformerMixin:
    """Provide a snake_case hook for ``leave_Call``."""

    # ruff: noqa: N802 - LibCST requires CamelCase hook names
    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        return self.leave_call(original_node, updated_node)

    def leave_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Snake_case override called by LibCST when exiting Call nodes."""
        del original_node
        return updated_node


class ExceptHandlerTransformerMixin:
    """Provide a snake_case hook for ``leave_ExceptHandler``."""

    # ruff: noqa: N802 - LibCST requires CamelCase hook names
    def leave_ExceptHandler(
        self,
        original_node: cst.ExceptHandler,
        updated_node: cst.ExceptHandler,
    ) -> cst.ExceptHandler:
        return self.leave_except_handler(original_node, updated_node)

    def leave_except_handler(
        self,
        original_node: cst.ExceptHandler,
        updated_node: cst.ExceptHandler,
    ) -> cst.ExceptHandler:
        """Snake_case override called by LibCST when exiting ExceptHandler nodes."""
        del original_node
        return updated_node


class WithTransformerMixin:
    """Provide a snake_case hook for ``leave_With``."""

    # ruff: noqa: N802 - LibCST requires CamelCase hook names
    def leave_With(self, original_node: cst.With, updated_node: cst.With) -> cst.With:
        return self.leave_with(original_node, updated_node)

    def leave_with(self, original_node: cst.With, updated_node: cst.With) -> cst.With:
        """Snake_case override called by LibCST when exiting With nodes."""
        del original_node
        return updated_node


class IfTransformerMixin:
    """Provide a snake_case hook for ``leave_If``."""

    # ruff: noqa: N802 - LibCST requires CamelCase hook names
    def leave_If(self, original_node: cst.If, updated_node: cst.If) -> cst.If:
        return self.leave_if(original_node, updated_node)

    def leave_if(self, original_node: cst.If, updated_node: cst.If) -> cst.If:
        """Snake_case override called by LibCST when exiting If nodes."""
        del original_node
        return updated_node
