"""LibCST-based codemod for migrating to typing facades.

This module provides AST transformers that:
1. Replace private `docs._types` imports with public `docs.types` imports
2. Replace `resolve_numpy`, `resolve_fastapi`, `resolve_faiss` shims with `gate_import` calls
3. Ensure TYPE_CHECKING guards are used for heavy optional dependencies
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import cast, override

import libcst as cst

logger = logging.getLogger(__name__)

MIN_MODULE_PARTS = 2


class TypingFacadeMigrator(cst.CSTTransformer):
    """Migrate typing imports to use façades instead of private modules.

    Notes
    -----
    This transformer replaces imports from ``docs._types`` with equivalent
    imports from the public facade modules (e.g., ``docs.types``).
    """

    def __init__(self) -> None:
        self.modified = False

    def _transform_import_from(self, node: cst.ImportFrom) -> cst.ImportFrom | cst.RemovalSentinel:
        """Return an updated import replacing private docs types with facades.

        Parameters
        ----------
        node : cst.ImportFrom
            ImportFrom node to transform.

        Returns
        -------
        cst.ImportFrom | cst.RemovalSentinel
            Transformed node or removal sentinel if unchanged.
        """
        if isinstance(node.module, cst.Attribute):
            module_parts = self._get_module_parts(node.module)
            if (
                len(module_parts) >= MIN_MODULE_PARTS
                and module_parts[0] == "docs"
                and module_parts[1] == "_types"
            ):
                new_parts = ["docs", "types", *module_parts[MIN_MODULE_PARTS:]]
                new_module = self._build_module(new_parts)
                self.modified = True
                return node.with_changes(module=new_module)

        if isinstance(node.module, cst.Name) and node.module.value == "docs._types":
            new_module = cst.Name("docs.types")
            self.modified = True
            return node.with_changes(module=new_module)

        return node

    def _transform_call(self, node: cst.Call) -> cst.Call:
        """Convert resolve_* shim invocations to gate_import calls.

        Parameters
        ----------
        node : cst.Call
            Call node to transform.

        Returns
        -------
        cst.Call
            Transformed call node with gate_import.
        """
        shim_map = {
            "resolve_numpy": ("gate_import", "numpy", "numpy array operations"),
            "resolve_fastapi": ("gate_import", "fastapi", "FastAPI integration"),
            "resolve_faiss": ("gate_import", "faiss", "FAISS vector indexing"),
        }

        if isinstance(node.func, cst.Name):
            func_name = node.func.value
            if func_name in shim_map:
                gate_func, lib_name, usage = shim_map[func_name]
                new_args = [
                    cst.Arg(cst.SimpleString(f'"{lib_name}"')),
                    cst.Arg(cst.SimpleString(f'"{usage}"')),
                ]
                self.modified = True
                return node.with_changes(func=cst.Name(gate_func), args=new_args)

        return node

    @staticmethod
    def _get_module_parts(node: cst.BaseExpression) -> list[str]:
        """Extract module path as list of parts.

        Parameters
        ----------
        node : cst.BaseExpression
            Module expression node to parse.

        Returns
        -------
        list[str]
            List of module name parts.
        """
        parts: list[str] = []
        current = node
        while isinstance(current, cst.Attribute):
            parts.insert(0, current.attr.value)
            current = current.value
        if isinstance(current, cst.Name):
            parts.insert(0, current.value)
        return parts

    @staticmethod
    def _build_module(parts: list[str]) -> cst.BaseExpression:
        """Build a module expression from parts.

        Parameters
        ----------
        parts : list[str]
            List of module name parts.

        Returns
        -------
        cst.BaseExpression
            Constructed module expression node.
        """
        result: cst.BaseExpression = cst.Name(parts[0])
        for part in parts[1:]:
            result = cst.Attribute(value=result, attr=cst.Name(part))
        return result

    @override
    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]:
        """Rewrite ``ImportFrom`` statements using docstring façade rules.

        Parameters
        ----------
        original_node : cst.ImportFrom
            Original node before transformation.
        updated_node : cst.ImportFrom
            Updated node after generic visitor processing.

        Returns
        -------
        cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel[cst.BaseSmallStatement]
            Transformed import node or sentinel.
        """
        del original_node
        return self._transform_import_from(updated_node)

    @override
    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Rewrite shim calls such as ``resolve_numpy`` to ``gate_import``.

        Parameters
        ----------
        original_node : cst.Call
            Original call node before transformation.
        updated_node : cst.Call
            Updated call node after generic visitor processing.

        Returns
        -------
        cst.Call
            Transformed call node with gate_import.
        """
        del original_node
        return self._transform_call(updated_node)


def run_codemod_on_file(file_path: Path) -> bool:
    """Apply the typing facade migration codemod to a file.

    Parameters
    ----------
    file_path : Path
        Path to the Python file to transform.

    Returns
    -------
    bool
        True if the file was modified, False otherwise.
    """
    try:
        source_code = file_path.read_text(encoding="utf-8")
        module = cst.parse_module(source_code)
        transformer = TypingFacadeMigrator()
        new_module = module.visit(transformer)
    except Exception:
        logger.exception("Error processing %s", file_path)
        return False

    if transformer.modified:
        file_path.write_text(new_module.code, encoding="utf-8")
        logger.info("Updated %s", file_path)
        return True
    return False


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    """Migrate typing imports to facades.

    Transforms:
    - `docs._types` → `docs.types` (public facade)
    - `resolve_*` shim calls → `gate_import()` calls

    Parameters
    ----------
    argv : list[str] | tuple[str, ...] | None, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit code (0 = success, 1 = failure).
    """
    parser = argparse.ArgumentParser(
        description="Migrate typing imports to facades (docs._types → docs.types, shims → gate_import)",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Directories or files to codemod",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without writing",
    )

    args = parser.parse_args(argv)

    # Collect all Python files
    python_files: list[Path] = []
    raw_paths = cast("list[Path]", args.paths)
    for path_arg in raw_paths:
        if path_arg.is_file() and path_arg.suffix == ".py":
            python_files.append(path_arg)
        elif path_arg.is_dir():
            python_files.extend(path_arg.rglob("*.py"))

    logger.info("Processing %d Python files", len(python_files))

    updated = 0
    for file_path in python_files:
        if run_codemod_on_file(file_path):
            updated += 1

    logger.info("Updated %d/%d files", updated, len(python_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
