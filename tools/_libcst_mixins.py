"""Common mixins for bridging LibCST CamelCase hooks to snake_case overrides."""

from __future__ import annotations

import libcst as cst


class ImportFromTransformerMixin:
    """Provide a snake_case hook for ``leave_ImportFrom``.

    Extended Summary
    ----------------
    This mixin bridges LibCST's CamelCase hook naming convention (required by
    the framework) to a snake_case override pattern preferred in this codebase.
    It allows transformers to implement ``leave_import_from`` instead of
    ``leave_ImportFrom``, improving code readability while maintaining LibCST
    compatibility. This pattern is used throughout the kgfoundry codebase for
    consistent transformer implementations.

    Notes
    -----
    The CamelCase method delegates to the snake_case method, which subclasses
    should override. The default implementation returns the updated node unchanged.
    """

    def leave_import_from(
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]:
        """Snake_case override called by LibCST when exiting ImportFrom nodes.

        Extended Summary
        ----------------
        This method is called by LibCST's transformation framework when exiting
        an ImportFrom node during AST traversal. Subclasses should override this
        method to implement custom transformation logic for ``from ... import ...``
        statements. The default implementation returns the updated node unchanged.

        Parameters
        ----------
        original_node : cst.ImportFrom
            Original ImportFrom node before any transformations. Typically unused
            but provided for reference or comparison.
        updated_node : cst.ImportFrom
            ImportFrom node after child transformations have been applied.
            This is the node that will be returned (or further transformed).

        Returns
        -------
        cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]
            The transformed ImportFrom node, RemovalSentinel to remove the node,
            or FlattenSentinel to flatten it into its parent's statement list.

        Notes
        -----
        Performance & Side Effects:
            Time complexity O(1). No I/O or global state mutations. Thread-safe
            for concurrent AST traversals (each transformer instance is isolated).

        See Also
        --------
        leave_Call : Similar hook for Call node transformations
        leave_With : Similar hook for With node transformations
        """
        del self, original_node
        return updated_node

    # Bridge CamelCase hook invoked by LibCST to the snake_case override.
    def leave_ImportFrom(  # noqa: N802
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]:
        return self.leave_import_from(original_node, updated_node)


class CallTransformerMixin:
    """Provide a snake_case hook for ``leave_Call``.

    Extended Summary
    ----------------
    This mixin bridges LibCST's CamelCase hook naming convention to a snake_case
    override pattern. It allows transformers to implement ``leave_call`` instead
    of ``leave_Call``, improving code readability while maintaining LibCST
    compatibility. Used for transforming function call expressions in the AST.

    Notes
    -----
    The CamelCase hook is provided automatically via attribute aliasing. Subclasses
    override :meth:`leave_call` and the mixin exposes the CamelCase hook that LibCST
    expects.
    """

    def leave_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Snake_case override called by LibCST when exiting Call nodes.

        Extended Summary
        ----------------
        This method is called by LibCST's transformation framework when exiting
        a Call node during AST traversal. Subclasses should override this method
        to implement custom transformation logic for function call expressions.
        The default implementation returns the updated node unchanged.

        Parameters
        ----------
        original_node : cst.Call
            Original Call node before any transformations. Typically unused but
            provided for reference or comparison.
        updated_node : cst.Call
            Call node after child transformations have been applied. This is the
            node that will be returned (or further transformed).

        Returns
        -------
        cst.Call
            The transformed Call node. Unlike ImportFrom, Call nodes cannot be
            removed or flattened (always returns Call).

        Notes
        -----
        Performance & Side Effects:
            Time complexity O(1). No I/O or global state mutations. Thread-safe
            for concurrent AST traversals.

        See Also
        --------
        leave_import_from : Similar hook for ImportFrom node transformations
        leave_with : Similar hook for With node transformations
        """
        del self, original_node
        return updated_node

    def leave_Call(  # noqa: N802
        self,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> cst.Call:
        return self.leave_call(original_node, updated_node)


class ExceptHandlerTransformerMixin:
    """Provide a snake_case hook for ``leave_ExceptHandler``.

    Extended Summary
    ----------------
    This mixin bridges LibCST's CamelCase hook naming convention to a snake_case
    override pattern. It allows transformers to implement ``leave_except_handler``
    instead of ``leave_ExceptHandler``, improving code readability while maintaining
    LibCST compatibility. Used for transforming exception handler clauses in the AST.

    Notes
    -----
    The CamelCase hook is provided automatically via attribute aliasing. Subclasses
    override :meth:`leave_except_handler` only.
    """

    def leave_except_handler(
        self,
        original_node: cst.ExceptHandler,
        updated_node: cst.ExceptHandler,
    ) -> cst.ExceptHandler:
        """Snake_case override called by LibCST when exiting ExceptHandler nodes.

        Extended Summary
        ----------------
        This method is called by LibCST's transformation framework when exiting
        an ExceptHandler node during AST traversal. Subclasses should override this
        method to implement custom transformation logic for exception handler clauses
        (``except ... as ...:``). The default implementation returns the updated node
        unchanged.

        Parameters
        ----------
        original_node : cst.ExceptHandler
            Original ExceptHandler node before any transformations. Typically unused
            but provided for reference or comparison.
        updated_node : cst.ExceptHandler
            ExceptHandler node after child transformations have been applied.
            This is the node that will be returned (or further transformed).

        Returns
        -------
        cst.ExceptHandler
            The transformed ExceptHandler node. Cannot be removed or flattened
            (always returns ExceptHandler).

        Notes
        -----
        Performance & Side Effects:
            Time complexity O(1). No I/O or global state mutations. Thread-safe
            for concurrent AST traversals.

        See Also
        --------
        leave_call : Similar hook for Call node transformations
        leave_if : Similar hook for If node transformations
        """
        del self, original_node
        return updated_node

    def leave_ExceptHandler(  # noqa: N802
        self,
        original_node: cst.ExceptHandler,
        updated_node: cst.ExceptHandler,
    ) -> cst.ExceptHandler:
        return self.leave_except_handler(original_node, updated_node)


class WithTransformerMixin:
    """Provide a snake_case hook for ``leave_With``.

    Extended Summary
    ----------------
    This mixin bridges LibCST's CamelCase hook naming convention to a snake_case
    override pattern. It allows transformers to implement ``leave_with`` instead
    of ``leave_With``, improving code readability while maintaining LibCST
    compatibility. Used for transforming context manager statements in the AST.

    Notes
    -----
    The CamelCase hook is provided automatically via attribute aliasing. Subclasses
    override :meth:`leave_with` only.
    """

    def leave_with(self, original_node: cst.With, updated_node: cst.With) -> cst.With:
        """Snake_case override called by LibCST when exiting With nodes.

        Extended Summary
        ----------------
        This method is called by LibCST's transformation framework when exiting
        a With node during AST traversal. Subclasses should override this method
        to implement custom transformation logic for context manager statements
        (``with ... as ...:``). The default implementation returns the updated node
        unchanged.

        Parameters
        ----------
        original_node : cst.With
            Original With node before any transformations. Typically unused but
            provided for reference or comparison.
        updated_node : cst.With
            With node after child transformations have been applied. This is the
            node that will be returned (or further transformed).

        Returns
        -------
        cst.With
            The transformed With node. Cannot be removed or flattened
            (always returns With).

        Notes
        -----
        Performance & Side Effects:
            Time complexity O(1). No I/O or global state mutations. Thread-safe
            for concurrent AST traversals.

        See Also
        --------
        leave_call : Similar hook for Call node transformations
        leave_if : Similar hook for If node transformations
        """
        del self, original_node
        return updated_node

    def leave_With(  # noqa: N802
        self,
        original_node: cst.With,
        updated_node: cst.With,
    ) -> cst.With:
        return self.leave_with(original_node, updated_node)


class IfTransformerMixin:
    """Provide a snake_case hook for ``leave_If``.

    Extended Summary
    ----------------
    This mixin bridges LibCST's CamelCase hook naming convention to a snake_case
    override pattern. It allows transformers to implement ``leave_if`` instead
    of ``leave_If``, improving code readability while maintaining LibCST
    compatibility. Used for transforming conditional statements in the AST.

    Notes
    -----
    The CamelCase hook is provided automatically via attribute aliasing. Subclasses
    override :meth:`leave_if` only.
    """

    def leave_if(self, original_node: cst.If, updated_node: cst.If) -> cst.If:
        """Snake_case override called by LibCST when exiting If nodes.

        Extended Summary
        ----------------
        This method is called by LibCST's transformation framework when exiting
        an If node during AST traversal. Subclasses should override this method
        to implement custom transformation logic for conditional statements
        (``if ...:``). The default implementation returns the updated node unchanged.

        Parameters
        ----------
        original_node : cst.If
            Original If node before any transformations. Typically unused but
            provided for reference or comparison.
        updated_node : cst.If
            If node after child transformations have been applied. This is the
            node that will be returned (or further transformed).

        Returns
        -------
        cst.If
            The transformed If node. Cannot be removed or flattened
            (always returns If).

        Notes
        -----
        Performance & Side Effects:
            Time complexity O(1). No I/O or global state mutations. Thread-safe
            for concurrent AST traversals.

        See Also
        --------
        leave_call : Similar hook for Call node transformations
        leave_with : Similar hook for With node transformations
        """
        del self, original_node
        return updated_node

    def leave_If(  # noqa: N802
        self,
        original_node: cst.If,
        updated_node: cst.If,
    ) -> cst.If:
        return self.leave_if(original_node, updated_node)
