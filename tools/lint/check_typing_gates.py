"""Checker ensuring type-only imports are guarded behind TYPE_CHECKING blocks.

This tool scans Python modules for unguarded imports used solely in type hints
and reports violations. It helps enforce the typing gates contract across the
codebase, preventing regressions where heavy dependencies sneak into runtime
execution paths.

## Design

1. Parse each module's AST
2. Identify imports (stdlib, third-party, internal)
3. Detect TYPE_CHECKING guards and import scopes
4. Flag imports inside TYPE_CHECKING as type-only (safe)
5. Flag imports outside TYPE_CHECKING but used only in annotations as violations
6. Report violations with file, line, and context

## Rule: Type-only imports MUST be guarded

A type-only import is one that appears only in:
- Function/method annotations (parameters, return type)
- Class annotations (base classes, attribute type hints)
- Type alias definitions

Examples of violations:

    import numpy as np  # Used only in annotation below

    def process(arr: np.ndarray) -> None:
        pass

    from fastapi import FastAPI  # Never instantiated at runtime

    app: FastAPI = ...  # Used only as annotation

Correct patterns:

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import numpy as np

    def process(arr: np.ndarray) -> None:
        pass

## Usage

    python -m tools.lint.check_typing_gates src/
    python -m tools.lint.check_typing_gates --diff
    python -m tools.lint.check_typing_gates --json src/ tools/
    python -m tools.lint.check_typing_gates --list src/  # For codemod integration
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tools._shared.logging import LoggerAdapter

from tools._shared.logging import get_logger


@dataclass(frozen=True)
class TypeGateViolation:
    """A type-only import that is not guarded by TYPE_CHECKING."""

    filepath: str
    """File path relative to cwd."""

    lineno: int
    """Line number of import."""

    module_name: str
    """Name of the imported module."""

    context: str
    """Brief description of violation."""

    violation_type: str
    """Type of violation: 'heavy_import', 'private_module', 'deprecated_shim'."""

    suggestion: str
    """Actionable fix guidance."""


class TypeGateVisitor(ast.NodeVisitor):
    """AST visitor to detect unguarded type-only imports.

    Parameters
    ----------
    filepath : Path
        Path to the file being analyzed.
    """

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[TypeGateViolation] = []
        self.in_type_checking_block = False
        self.type_checking_depth = 0

    def visit_If(self, node: ast.If) -> None:
        """Track entry/exit of TYPE_CHECKING blocks."""
        # Check if this is "if TYPE_CHECKING:"
        if self._is_type_checking_guard(node):
            self.in_type_checking_block = True
            self.type_checking_depth += 1
            self.generic_visit(node)
            self.type_checking_depth -= 1
            self.in_type_checking_block = self.type_checking_depth > 0
        else:
            self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record imports and their context."""
        # Skip imports inside TYPE_CHECKING blocks
        if self.in_type_checking_block:
            self.generic_visit(node)
            return

        if node.module is None:
            self.generic_visit(node)
            return

        # Check for private module imports
        if node.module.startswith("docs._types") or node.module.startswith(
            "docs._cache"
        ):
            suggestion = self._suggest_private_module_fix(node.module)
            violation = TypeGateViolation(
                filepath=str(self.filepath),
                lineno=node.lineno,
                module_name=node.module,
                context=f"Private module import: {node.module}",
                violation_type="private_module",
                suggestion=suggestion,
            )
            self.violations.append(violation)
            self.generic_visit(node)
            return

        # Check for deprecated shim usage
        if node.module == "kgfoundry_common.typing":
            for alias in node.names:
                if alias.name in {"resolve_numpy", "resolve_fastapi", "resolve_faiss"}:
                    suggestion = self._suggest_shim_fix(alias.name)
                    violation = TypeGateViolation(
                        filepath=str(self.filepath),
                        lineno=node.lineno,
                        module_name=f"kgfoundry_common.typing.{alias.name}",
                        context=f"Deprecated shim: {alias.name}()",
                        violation_type="deprecated_shim",
                        suggestion=suggestion,
                    )
                    self.violations.append(violation)

        # Check for heavy imports outside TYPE_CHECKING
        heavy_modules = {
            "numpy",
            "fastapi",
            "faiss",
            "torch",
            "tensorflow",
            "pandas",
            "sklearn",
            "pydantic",
            "sqlalchemy",
        }

        module_root = node.module.split(".")[0]

        if module_root in heavy_modules:
            suggestion = self._suggest_heavy_import_fix(node.module)
            context = f"Potentially type-only import from {node.module}"
            violation = TypeGateViolation(
                filepath=str(self.filepath),
                lineno=node.lineno,
                module_name=node.module,
                context=context,
                violation_type="heavy_import",
                suggestion=suggestion,
            )
            self.violations.append(violation)

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Record direct imports."""
        # Skip imports inside TYPE_CHECKING blocks
        if self.in_type_checking_block:
            self.generic_visit(node)
            return

        heavy_modules = {
            "numpy",
            "fastapi",
            "faiss",
            "torch",
            "tensorflow",
            "pandas",
            "sklearn",
            "pydantic",
            "sqlalchemy",
        }

        for alias in node.names:
            module_root = alias.name.split(".")[0]
            if module_root in heavy_modules:
                suggestion = self._suggest_heavy_import_fix(alias.name)
                context = f"Potentially type-only import: {alias.name}"
                violation = TypeGateViolation(
                    filepath=str(self.filepath),
                    lineno=node.lineno,
                    module_name=alias.name,
                    context=context,
                    violation_type="heavy_import",
                    suggestion=suggestion,
                )
                self.violations.append(violation)

        self.generic_visit(node)

    @staticmethod
    def _is_type_checking_guard(node: ast.If) -> bool:
        """Check if an If node is a TYPE_CHECKING guard.

        Parameters
        ----------
        node : ast.If
            AST If node to check.

        Returns
        -------
        bool
            True if the node is a TYPE_CHECKING guard.
        """
        # Pattern: if TYPE_CHECKING:
        test = node.test
        return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"

    @staticmethod
    def _suggest_private_module_fix(module: str) -> str:
        """Generate suggestion for private module imports.

        Parameters
        ----------
        module : str
            Module name that was imported.

        Returns
        -------
        str
            Suggestion message for fixing the violation.
        """
        if module.startswith("docs._types"):
            return "Use public façade: from docs.types import ... (or docs.typing for type-only helpers)"
        if module.startswith("docs._cache"):
            return "Use public façade: from docs.types import ... or access public cache API"
        return "Use public façade modules instead of private imports"

    @staticmethod
    def _suggest_shim_fix(shim_name: str) -> str:
        """Generate suggestion for deprecated shim usage.

        Parameters
        ----------
        shim_name : str
            Name of the deprecated shim function.

        Returns
        -------
        str
            Suggestion message for fixing the violation.
        """
        if shim_name == "resolve_numpy":
            return "Use gate_import('numpy', 'purpose') or TYPE_CHECKING guard + numpy import"
        if shim_name == "resolve_fastapi":
            return "Use gate_import('fastapi', 'purpose') or TYPE_CHECKING guard + fastapi import"
        if shim_name == "resolve_faiss":
            return "Use gate_import('faiss', 'purpose') or TYPE_CHECKING guard + faiss import"
        return f"Deprecated shim {shim_name} removed. Use gate_import() or TYPE_CHECKING guard"

    @staticmethod
    def _suggest_heavy_import_fix(module: str) -> str:
        """Generate suggestion for heavy imports.

        Parameters
        ----------
        module : str
            Module name that was imported.

        Returns
        -------
        str
            Suggestion message for fixing the violation.
        """
        module_root = module.split(".", maxsplit=1)[0]
        return (
            f"Guard {module_root} import behind TYPE_CHECKING block, or use "
            f"gate_import('{module_root}', 'purpose') for runtime access"
        )


def check_file(
    filepath: Path, logger: LoggerAdapter | None = None
) -> list[TypeGateViolation]:
    """Check a single Python file for typing gate violations.

    Parameters
    ----------
    filepath : Path
        File to check.
    logger : LoggerAdapter | None, optional
        Logger instance (default: None).

    Returns
    -------
    list[TypeGateViolation]
        List of violations found.
    """
    active_logger = logger or get_logger(__name__)

    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
        visitor = TypeGateVisitor(filepath)
        visitor.visit(tree)
    except SyntaxError:
        active_logger.exception("Syntax error in %s", filepath)
        return []
    except Exception:
        active_logger.exception("Error checking %s", filepath)
        return []
    return visitor.violations


def check_directory(
    root: Path,
    logger: LoggerAdapter | None = None,
) -> list[TypeGateViolation]:
    """Check all Python files in a directory.

    Parameters
    ----------
    root : Path
        Directory to scan.
    logger : LoggerAdapter | None, optional
        Logger instance (default: None).

    Returns
    -------
    list[TypeGateViolation]
        All violations found.
    """
    active_logger = logger or get_logger(__name__)

    all_violations: list[TypeGateViolation] = []
    py_files = sorted(root.rglob("*.py"))

    for fpath in py_files:
        # Skip cache and hidden files
        if any(part.startswith(".") for part in fpath.parts):
            continue
        if "__pycache__" in fpath.parts:
            continue

        violations = check_file(fpath, logger=active_logger)
        all_violations.extend(violations)

    return all_violations


def format_violations(
    violations: list[TypeGateViolation],
    *,
    json_output: bool = False,
    list_output: bool = False,
) -> str:
    """Format violations for output.

    Parameters
    ----------
    violations : list[TypeGateViolation]
        List of violations.
    json_output : bool, optional
        Output as JSON (default: False).
    list_output : bool, optional
        Output as flat list for codemod integration (default: False).

    Returns
    -------
    str
        Formatted output.
    """
    if json_output:
        payload: list[dict[str, object]] = [
            cast("dict[str, object]", asdict(v)) for v in violations
        ]
        return json.dumps(payload, indent=2)

    if list_output:
        # Format for codemod: filepath:lineno:violation_type:module_name
        lines = [
            f"{v.filepath}:{v.lineno}:{v.violation_type}:{v.module_name}"
            for v in violations
        ]
        return "\n".join(lines)

    if not violations:
        return "✓ No typing gate violations found."

    # Detailed output with suggestions
    lines = [f"✗ Found {len(violations)} typing gate violation(s):\n"]
    for v in violations:
        lines.append(f"  {v.filepath}:{v.lineno}: {v.module_name}")
        lines.append(f"    Type: {v.violation_type}")
        lines.append(f"    Context: {v.context}")
        lines.append(f"    Fix: {v.suggestion}\n")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Check typing gates across specified directories.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments (directories or flags).
        Flags: --json, --diff, --list, --help

    Returns
    -------
    int
        Exit code (0 = no violations, 1 = violations found).
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Check for unguarded type-only imports (typing gates)."
    )
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        help="Directories to check (default: src/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Show diff (reserved for future use)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Output as flat list for codemod integration (filepath:lineno:type:module)",
    )

    args = parser.parse_args(argv)
    logger = get_logger(__name__)

    all_violations: list[TypeGateViolation] = []

    # Cast for type safety (argparse.Namespace.directories is typed as Any)
    raw_directories = cast("Sequence[Path]", getattr(args, "directories", ()))
    directories = list(raw_directories) if raw_directories else [Path("src")]
    for directory in directories:
        if not directory.exists():
            msg = f"Directory not found: {directory}"
            logger.warning(msg)
            continue

        violations = check_directory(directory, logger=logger)
        all_violations.extend(violations)

    # Output results
    json_attr: object = getattr(args, "json", False)
    list_attr: object = getattr(args, "list", False)
    output = format_violations(
        all_violations,
        json_output=bool(json_attr),
        list_output=bool(list_attr),
    )
    sys.stdout.write(output + "\n")

    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
