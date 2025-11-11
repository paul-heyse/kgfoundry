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

try:  # pragma: no cover - executed in tooling context
    from kgfoundry_common.typing.heavy_deps import EXTRAS_HINT as _EXTRAS_HINT
except ImportError:  # pragma: no cover - when package not importable
    _EXTRAS_HINT: dict[str, str] = {}

try:  # pragma: no cover - executed in tooling context
    from codeintel_rev.typing import HEAVY_DEPS as _HEAVY_DEPS_SOURCE
except ImportError:  # pragma: no cover - when package not importable
    _HEAVY_DEPS_SOURCE: dict[str, str | None] = {}

_DEFAULT_HEAVY_MODULES = {
    "numpy",
    "faiss",
    "duckdb",
    "torch",
    "tensorflow",
    "pandas",
    "sklearn",
    "pydantic",
    "sqlalchemy",
    "fastapi",
    "httpx",
    "onnxruntime",
    "pyserini",
}

HEAVY_MODULES = set(_DEFAULT_HEAVY_MODULES)
HEAVY_MODULES.update(_HEAVY_DEPS_SOURCE)


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

    end_lineno: int | None = None
    """Ending line number (for autofix)."""

    col_offset: int = 0
    """Column offset of the statement (autofix restriction)."""

    fixable: bool = False
    """True when the violation can be automatically wrapped."""


class TypeGateVisitor(ast.NodeVisitor):
    """AST visitor to detect unguarded type-only imports.

    Parameters
    ----------
    filepath : Path
        Path to the file being analyzed.
    """

    def __init__(self, filepath: Path, heavy_modules: set[str]) -> None:
        self.filepath = filepath
        self.violations: list[TypeGateViolation] = []
        self.in_type_checking_block = False
        self.type_checking_depth = 0
        self.heavy_modules = heavy_modules

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
        if node.module.startswith("docs._types") or node.module.startswith("docs._cache"):
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

        module_root = node.module.split(".")[0]

        if module_root in self.heavy_modules:
            suggestion = self._suggest_heavy_import_fix(node.module)
            context = f"Potentially type-only import from {node.module}"
            violation = TypeGateViolation(
                filepath=str(self.filepath),
                lineno=node.lineno,
                module_name=node.module,
                context=context,
                violation_type="heavy_import",
                suggestion=suggestion,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                col_offset=getattr(node, "col_offset", 0),
                fixable=getattr(node, "col_offset", 0) == 0,
            )
            self.violations.append(violation)

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Record direct imports."""
        # Skip imports inside TYPE_CHECKING blocks
        if self.in_type_checking_block:
            self.generic_visit(node)
            return

        heavy_aliases = []
        for alias in node.names:
            module_root = alias.name.split(".")[0]
            if module_root in self.heavy_modules:
                heavy_aliases.append(alias.name)

        if not heavy_aliases:
            self.generic_visit(node)
            return

        mixed = len(heavy_aliases) != len(node.names)
        module_list = ", ".join(heavy_aliases)
        suggestion = self._suggest_heavy_import_fix(module_list)
        context = f"Potentially type-only import: {module_list}"
        violation = TypeGateViolation(
            filepath=str(self.filepath),
            lineno=node.lineno,
            module_name=module_list,
            context=context,
            violation_type="heavy_import",
            suggestion=suggestion,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            col_offset=getattr(node, "col_offset", 0),
            fixable=(not mixed) and getattr(node, "col_offset", 0) == 0,
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
        base = (
            f"Guard {module_root} import behind TYPE_CHECKING block, or use "
            f"gate_import('{module_root}', 'purpose') for runtime access"
        )
        extra_hint = _format_install_hint(module_root)
        if extra_hint:
            return f"{base}. Install via {extra_hint}"
        return base


def _format_install_hint(module_root: str) -> str | None:
    hint = _EXTRAS_HINT.get(module_root)
    if not hint:
        return None
    if " or " in hint:
        return " or ".join(
            f"pip install codeintel-rev[{option.strip()}]" for option in hint.split(" or ")
        )
    return f"pip install codeintel-rev[{hint}]"


def check_file(
    filepath: Path,
    heavy_modules: set[str],
    logger: LoggerAdapter | None = None,
) -> list[TypeGateViolation]:
    """Check a single Python file for typing gate violations.

    Parameters
    ----------
    filepath : Path
        File to check.
    heavy_modules : set[str]
        Heavy modules that must be guarded.
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
        visitor = TypeGateVisitor(filepath, heavy_modules)
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
    heavy_modules: set[str],
    logger: LoggerAdapter | None = None,
) -> list[TypeGateViolation]:
    """Check all Python files in a directory.

    Parameters
    ----------
    root : Path
        Directory to scan.
    heavy_modules : set[str]
        Heavy modules that must be guarded.
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

        violations = check_file(fpath, heavy_modules, logger=active_logger)
        all_violations.extend(violations)

    return all_violations


def _has_type_checking_import(tree: ast.Module) -> bool:
    """Return True when module imports TYPE_CHECKING from typing.

    Returns
    -------
    bool
        ``True`` when TYPE_CHECKING is imported.
    """
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                if alias.name == "TYPE_CHECKING":
                    return True
    return False


def _insert_type_checking_import(lines: list[str], tree: ast.Module) -> None:
    """Ensure `from typing import TYPE_CHECKING` exists near the top of the file."""
    insert_idx = 0
    if lines and lines[0].startswith("#!"):
        insert_idx += 1

    docstring_end = 0
    if tree.body and isinstance(tree.body[0], ast.Expr):
        expr = tree.body[0]
        if isinstance(expr.value, ast.Constant) and isinstance(expr.value.value, str):
            docstring_end = getattr(expr, "end_lineno", expr.lineno)
    insert_idx = max(insert_idx, docstring_end)

    while insert_idx < len(lines) and lines[insert_idx].startswith("from __future__ import"):
        insert_idx += 1

    lines.insert(insert_idx, "from typing import TYPE_CHECKING")
    lines.insert(insert_idx + 1, "")


def _indent_block(block: list[str]) -> list[str]:
    """Indent the provided code block by four spaces.

    Returns
    -------
    list[str]
        Indented block.
    """
    return ["    " + line if line.strip() else "    " for line in block]


def apply_fixes(
    filepath: Path,
    violations: list[TypeGateViolation],
    logger: LoggerAdapter | None = None,
) -> bool:
    """Guard fixable heavy imports behind TYPE_CHECKING blocks.

    Returns
    -------
    bool
        ``True`` when the file was modified.
    """
    fixable = [v for v in violations if v.violation_type == "heavy_import" and v.fixable]
    if not fixable:
        return False

    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()
    module = ast.parse(text, filename=str(filepath))

    if not _has_type_checking_import(module):
        _insert_type_checking_import(lines, module)

    for violation in sorted(fixable, key=lambda v: v.lineno, reverse=True):
        start = violation.lineno - 1
        end = (violation.end_lineno or violation.lineno) - 1
        snippet = lines[start : end + 1]
        guarded = ["if TYPE_CHECKING:", *_indent_block(snippet)]
        lines[start : end + 1] = guarded

    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if logger:
        logger.info("Guarded %s heavy import(s) in %s", len(fixable), filepath)
    return True


def _apply_autofixes(
    violations_by_path: dict[Path, list[TypeGateViolation]],
    heavy_modules: set[str],
    logger: LoggerAdapter | None = None,
) -> tuple[list[TypeGateViolation], set[str]]:
    """Apply autofixes for fixable violations and return refreshed results.

    Returns
    -------
    tuple[list[TypeGateViolation], set[str]]
        Refreshed violations and filepaths that were modified.
    """
    refreshed_paths: list[Path] = []
    for path, violations in violations_by_path.items():
        if not path.exists():
            continue
        if apply_fixes(path, violations, logger):
            refreshed_paths.append(path)

    if not refreshed_paths:
        return [], set()

    refreshed: list[TypeGateViolation] = []
    for path in refreshed_paths:
        refreshed.extend(check_file(path, heavy_modules, logger))

    return refreshed, {str(path) for path in refreshed_paths}


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
        lines = [f"{v.filepath}:{v.lineno}:{v.violation_type}:{v.module_name}" for v in violations]
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
    parser.add_argument(
        "--write",
        action="store_true",
        help="Automatically guard fixable heavy imports behind TYPE_CHECKING",
    )

    args = parser.parse_args(argv)
    logger = get_logger(__name__)

    all_violations: list[TypeGateViolation] = []
    violations_by_path: dict[Path, list[TypeGateViolation]] = {}

    # Cast for type safety (argparse.Namespace.directories is typed as Any)
    raw_directories = cast("Sequence[Path]", getattr(args, "directories", ()))
    directories = list(raw_directories) if raw_directories else [Path("src")]
    for directory in directories:
        if not directory.exists():
            msg = f"Directory not found: {directory}"
            logger.warning(msg)
            continue

        violations = check_directory(directory, HEAVY_MODULES, logger=logger)
        all_violations.extend(violations)
        for violation in violations:
            violations_by_path.setdefault(Path(violation.filepath), []).append(violation)

    if getattr(args, "write", False):
        refreshed, stale_keys = _apply_autofixes(violations_by_path, HEAVY_MODULES, logger)
        if stale_keys:
            all_violations = [v for v in all_violations if v.filepath not in stale_keys]
            all_violations.extend(refreshed)

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
