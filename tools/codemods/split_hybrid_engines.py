"""Codemod to migrate hybrid engine imports to the split engine modules."""

from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
from libcst.helpers import get_full_name_for_node


class SplitHybridEnginesCommand(VisitorBasedCodemodCommand):
    """Rewrite legacy Splade/BM25 manager imports to the new engine modules."""

    DESCRIPTION: str = "Replace Splade/BM25 manager runtime imports with the split engine modules."

    def leave(
        self,
        _original_node: cst.CSTNode,
        updated_node: cst.CSTNode,
    ) -> cst.CSTNode:
        """Rewrite relevant nodes when leaving them during traversal.

        Returns
        -------
        cst.CSTNode
            Possibly rewritten node.
        """
        if isinstance(updated_node, cst.ImportFrom):
            module_name = self._module_name(updated_node)
            if module_name == "codeintel_rev.io.splade_manager":
                return self._rewrite_import(
                    updated_node,
                    symbol="SpladeManager",
                    new_module="codeintel_rev.io.splade_engine",
                    new_symbol="SPLADEEngine",
                )
            if module_name == "codeintel_rev.io.bm25_manager":
                return self._rewrite_import(
                    updated_node,
                    symbol="BM25Manager",
                    new_module="codeintel_rev.io.bm25_engine",
                    new_symbol="BM25Engine",
                )
        if isinstance(updated_node, cst.Attribute) and m.matches(
            updated_node.attr, m.Name("query")
        ):
            return updated_node.with_changes(attr=cst.Name("search"))
        return updated_node

    @staticmethod
    def _module_name(node: cst.ImportFrom) -> str | None:
        if node.module is None:
            return None
        try:
            return get_full_name_for_node(node.module)
        except AttributeError:
            return None

    def _rewrite_import(
        self,
        node: cst.ImportFrom,
        *,
        symbol: str,
        new_module: str,
        new_symbol: str,
    ) -> cst.ImportFrom:
        module_name = self._module_name(node)
        names = node.names
        if isinstance(names, cst.ImportStar):
            return node
        name_list = list(names)
        kept: list[cst.ImportAlias] = []
        removed = False
        for alias in name_list:
            if not isinstance(alias, cst.ImportAlias):
                kept.append(alias)
                continue
            if m.matches(alias, m.ImportAlias(name=m.Name(symbol))):
                RemoveImportsVisitor.remove_unused_import(
                    self.context,
                    module_name or "",
                    symbol,
                )
                AddImportsVisitor.add_needed_import(self.context, new_module, new_symbol)
                removed = True
            else:
                kept.append(alias)
        if removed:
            return node.with_changes(names=tuple(kept))
        return node


def apply_split_hybrid_engines(context: CodemodContext) -> SplitHybridEnginesCommand:
    """Create codemod command for splitting hybrid engines.

    Parameters
    ----------
    context : CodemodContext
        Codemod execution context.

    Returns
    -------
    SplitHybridEnginesCommand
        Configured codemod command instance.
    """
    return SplitHybridEnginesCommand(context)
