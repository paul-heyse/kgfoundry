#!/usr/bin/env python3
"""Static repo inspection utilities for dependency and documentation hygiene.

This module powers the `tools/repo_scan.py` CLI, which enumerates Python files
under a folder, extracts import edges, public APIs, docstring coverage, typing
coverage, complexity proxies, git activity, and a light tests-to-modules map.
Everything is intentionally built on the Python standard library so it can be
invoked anywhere—developers, CI, or even pre-commit hooks—without depending on
framework-specific tooling or heavyweight parsers.

Examples
--------
Scan the `src/` tree inside the repository and emit both JSON and DOT outputs::

    python tools/repo_scan.py . --repo-root . \
        --include-subdir src --include-subdir tests \
        --out-json repo_metrics.json --out-dot import_graph.dot

The JSON payload mirrors the structure documented in the Agent Operating
Protocol (AOP) context: module metrics feed automation (items 3-8) while the DOT
file can be rendered with Graphviz for quick visual inspection of imports.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import shutil
import sys
import time
import tokenize
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field, replace
from importlib import util as importlib_util
from pathlib import Path
from typing import Any, cast

from kgfoundry_common.subprocess_utils import SubprocessError, run_subprocess
from tools.repo_scan_griffe import DocstringStyle, collect_api_symbols_with_griffe
from tools.repo_scan_libcst import collect_imports_with_libcst

logger = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "__pycache__",
    "site-packages",
    "node_modules",
}

GIT_COMMAND_TIMEOUT = 60

# --------------------------
# utils
# --------------------------


def iter_py_files(
    root: Path,
    include_subdirs: tuple[str, ...] | None = None,
) -> Iterator[Path]:
    """Yield Python source files while skipping generated directories.

    Parameters
    ----------
    root : Path
        Root directory to traverse recursively.
    include_subdirs : tuple[str, ...] | None, optional
        Relative subdirectories that should be scanned; defaults to all.

    Yields
    ------
    Path
        Absolute paths to ``*.py`` files that are not inside ``SKIP_DIRS``.
    """
    root = root.resolve()
    include_parts = tuple(Path(subdir).parts for subdir in include_subdirs or ())
    for p in root.rglob("*.py"):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if include_parts and not _path_has_prefix(rel, include_parts):
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p


def module_name_from_path(
    scan_root: Path,
    path: Path,
    *,
    strip_prefixes: tuple[str, ...] = (),
) -> str:
    """Convert a filesystem path under ``scan_root`` into a dotted module path.

    Parameters
    ----------
    scan_root : Path
        Directory that anchors the module tree.
    path : Path
        Actual file path discovered while scanning.
    strip_prefixes : tuple[str, ...], optional
        Optional top-level path components to remove from module names.

    Returns
    -------
    str
        Dotted module path (``package.module``) relative to ``scan_root``.
    """
    rel = path.resolve().relative_to(scan_root.resolve())
    parts = list(rel.parts)
    for prefix in strip_prefixes:
        if parts and parts[0] == prefix:
            parts = parts[1:]
            break
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts).replace(os.sep, ".")


def _path_has_prefix(rel_path: Path, prefixes: tuple[tuple[str, ...], ...]) -> bool:
    """Return True if ``rel_path`` begins with any of the provided prefixes.

    Parameters
    ----------
    rel_path : Path
        Relative path being evaluated.
    prefixes : tuple[tuple[str, ...], ...]
        Collection of prefix tuples to compare against.

    Returns
    -------
    bool
        ``True`` when the path begins with any of the prefixes, otherwise False.
    """
    rel_parts = rel_path.parts
    for prefix in prefixes:
        if len(rel_parts) >= len(prefix) and rel_parts[: len(prefix)] == prefix:
            return True
    return False


def safe_parse_ast(path: Path) -> ast.Module | None:
    """Parse a Python file into an AST, swallowing syntax errors gracefully.

    Parameters
    ----------
    path : Path
        Source file to parse.

    Returns
    -------
    ast.Module | None
        Parsed module tree when parsing succeeds; ``None`` when parsing fails.
    """
    try:
        with tokenize.open(path) as f:
            src = f.read()
        return ast.parse(src, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def file_loc(path: Path) -> int:
    """Count the number of lines for a file without loading it entirely.

    Parameters
    ----------
    path : Path
        File whose line count is needed.

    Returns
    -------
    int
        Line count or zero if the file cannot be opened.
    """
    try:
        with Path(path).open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# --------------------------
# AST analyses
# --------------------------


@dataclass(frozen=True)
class DocStats:
    """Bookkeeping for docstring coverage derived from an AST walk.

    Attributes
    ----------
    module_doc : bool
        Whether the module defines a top-level docstring.
    class_total : int
        Total number of class definitions discovered.
    class_with_doc : int
        Number of classes that include a docstring.
    func_total : int
        Total number of function or coroutine definitions discovered.
    func_with_doc : int
        Number of functions/coroutines that include a docstring.
    """

    module_doc: bool
    class_total: int
    class_with_doc: int
    func_total: int
    func_with_doc: int


@dataclass(frozen=True)
class TypeHintStats:
    """Type-hint coverage snapshot for a module.

    Attributes
    ----------
    functions : int
        Total number of (async) functions encountered.
    annotated_returns : int
        Number of functions with an explicit return annotation.
    total_params : int
        Total parameters counted across functions.
    annotated_params : int
        Parameters that include annotations.
    """

    functions: int
    annotated_returns: int
    total_params: int
    annotated_params: int


@dataclass(frozen=True)
class ComplexityStats:
    """Lightweight complexity proxies gathered without third-party tools.

    Attributes
    ----------
    branch_points : int
        Approximate cyclomatic complexity measured via branch statements.
    max_nesting : int
        Maximum nested block depth discovered in the AST.
    """

    branch_points: int
    max_nesting: int


@dataclass(frozen=True)
class ModuleReport:
    """Aggregate metadata for a single Python module in the scan.

    Attributes
    ----------
    module : str
        Dotted module name relative to the scan root.
    path : str
        Absolute filesystem path to the module.
    is_test : bool
        Whether the module looks like a pytest/test module.
    imports : list[str]
        Import targets referenced by the module.
    public_api : list[str]
        Exported functions/classes as inferred by :func:`collect_public_api`.
    public_api_details : list[dict[str, str]]
        Signature/doc summaries for public API symbols.
    raises : dict[str, list[str]]
        Mapping of function names to exceptions raised.
    doc : DocStats
        Docstring coverage counters.
    typing : TypeHintStats
        Type annotation coverage counters.
    complexity : ComplexityStats
        Proxy metrics for per-module complexity.
    loc : int
        Raw line count for the file.
    parse_ok : bool
        Indicates whether ``ast.parse`` succeeded.
    parse_error : str | None
        Optional marker describing parse failures.
    imports_cst : dict[str, Any] | None
        Optional LibCST-derived import/export snapshot.
    """

    module: str
    path: str
    is_test: bool
    imports: list[str]
    public_api: list[str]
    doc: DocStats
    typing: TypeHintStats
    complexity: ComplexityStats
    loc: int
    parse_ok: bool
    parse_error: str | None = None
    imports_cst: dict[str, Any] | None = None
    test_count: int = 0
    has_tests: bool = False
    public_api_without_tests: list[str] = field(default_factory=list)
    public_api_details: list[dict[str, str]] = field(default_factory=list)
    raises: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class TestScanConfig:
    """Immutable configuration for collecting relevant test modules."""

    repo_root: Path
    tests_subdirs: tuple[str, ...]
    strip_prefixes: tuple[str, ...]
    target_modules: set[str]
    exclude_paths: set[str]
    use_libcst: bool = False


@dataclass(frozen=True)
class PayloadOptions:
    """Configuration for assembling the JSON payload."""

    scan_root: Path
    repo_root: Path
    with_griffe: bool
    with_libcst: bool
    docstyle: DocstringStyle


def collect_imports(modname: str, tree: ast.Module) -> list[str]:
    """Gather import targets referenced by a module.

    Parameters
    ----------
    modname : str
        Dotted name of the module being analyzed.
    tree : ast.Module
        Parsed module tree.

    Returns
    -------
    list[str]
        De-duplicated list of import targets including resolved relatives.
    """
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                target = _resolve_from_alias_target(modname, node, alias)
                if target:
                    imports.append(target)
    return _dedupe_preserve_order(imports)


def _resolve_from_alias_target(
    module_name: str, node: ast.ImportFrom, alias: ast.alias
) -> str | None:
    """Resolve the import target represented by ``alias``.

    Parameters
    ----------
    module_name : str
        Dotted name of the module being analyzed.
    node : ast.ImportFrom
        Import statement node containing alias information.
    alias : ast.alias
        Specific alias entry to resolve.

    Returns
    -------
    str | None
        Fully qualified module path for the alias, if resolvable.
    """
    level = getattr(node, "level", 0) or 0
    if level > 0:
        relative = "." * level
        if node.module:
            relative += node.module
            if alias.name and alias.name != "*":
                relative += f".{alias.name}"
        elif alias.name and alias.name != "*":
            relative += alias.name
        try:
            return importlib_util.resolve_name(relative or ".", module_name)
        except (ImportError, ValueError):
            return None
    if alias.name == "*":
        return node.module
    if node.module:
        return f"{node.module}.{alias.name}"
    return alias.name or None


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Return the unique values from ``items`` while preserving order.

    Parameters
    ----------
    items : Iterable[str]
        Sequence of strings whose duplicates should be removed.

    Returns
    -------
    list[str]
        De-duplicated list preserving original order.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def collect_public_api(tree: ast.Module) -> list[str]:
    """Return the public top-level symbols exported by a module.

    Parameters
    ----------
    tree : ast.Module
        Parsed module tree.

    Returns
    -------
    list[str]
        Symbols defined at module scope, honoring ``__all__`` overrides.
    """
    if not isinstance(tree, ast.Module):
        return []
    explicit = _extract_dunder_all(tree)
    if explicit is not None:
        return explicit
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    ]


def _annotation_to_str(node: ast.AST | None) -> str:
    """Return the string representation of an annotation or default value.

    Returns
    -------
    str
        Rendered annotation or an empty string when unavailable.
    """
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _doc_one_liner(text: str | None) -> str:
    """Return the first non-empty line from ``text``.

    Returns
    -------
    str
        A single trimmed line or an empty string when ``text`` is blank.
    """
    if not text:
        return ""
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _format_parameters(args: ast.arguments) -> list[str]:
    """Render human-friendly parameter strings for ``args``.

    Returns
    -------
    list[str]
        Parameter representations suitable for signature display.
    """
    params: list[str] = []
    total_pos = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults = list(args.defaults or [])
    default_offset = len(total_pos) - len(defaults)

    for index, arg in enumerate(total_pos):
        default_value = defaults[index - default_offset] if index >= default_offset else None
        params.append(_format_arg(arg, default_value))

    if args.vararg:
        params.append(_format_arg(args.vararg, None, prefix="*"))

    if args.kwonlyargs:
        if not args.vararg:
            params.append("*")
        kw_defaults = list(args.kw_defaults or [])
        if len(kw_defaults) < len(args.kwonlyargs):
            kw_defaults.extend([None] * (len(args.kwonlyargs) - len(kw_defaults)))
        for kwarg, default in zip(args.kwonlyargs, kw_defaults, strict=False):
            params.append(_format_arg(kwarg, default))

    if args.kwarg:
        params.append(_format_arg(args.kwarg, None, prefix="**"))

    return params


def _format_arg(arg: ast.arg, default: ast.AST | None, prefix: str = "") -> str:
    """Format a single argument with annotation/defaults.

    Returns
    -------
    str
        String representation of the argument.
    """
    name = f"{prefix}{arg.arg}"
    annotation = _annotation_to_str(arg.annotation)
    if annotation:
        name += f": {annotation}"
    if default is not None:
        default_text = _annotation_to_str(default)
        if default_text:
            name += f" = {default_text}"
    return name


def _function_signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a repr-style signature string for ``fn``.

    Returns
    -------
    str
        Signature string containing parameters and optional return type.
    """
    params = ", ".join(_format_parameters(fn.args))
    ret = _annotation_to_str(fn.returns)
    suffix = f" -> {ret}" if ret else ""
    return f"{fn.name}({params}){suffix}"


def _class_signature(cls: ast.ClassDef) -> str:
    """Return a class signature showing its bases.

    Returns
    -------
    str
        Class depiction including base classes when available.
    """
    bases = ", ".join(filter(None, (_annotation_to_str(base) for base in cls.bases)))
    return f"class {cls.name}({bases})" if bases else f"class {cls.name}"


def collect_public_api_details(
    tree: ast.Module,
    module_path: Path,
    allowed_names: set[str],
) -> list[dict[str, str]]:
    """Emit signature/doc summaries for public API members.

    Returns
    -------
    list[dict[str, str]]
        Sequence describing each exported symbol.
    """
    details: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in allowed_names:
            sig = _function_signature(node)
            details.append(
                {
                    "name": node.name,
                    "kind": "function",
                    "signature": sig,
                    "doc_one_liner": _doc_one_liner(ast.get_docstring(node, clean=True)),
                    "defined_at": f"{module_path}:{node.lineno}",
                }
            )
        elif isinstance(node, ast.ClassDef) and node.name in allowed_names:
            details.append(
                {
                    "name": node.name,
                    "kind": "class",
                    "signature": _class_signature(node),
                    "doc_one_liner": _doc_one_liner(ast.get_docstring(node, clean=True)),
                    "defined_at": f"{module_path}:{node.lineno}",
                }
            )
    return details


def _exception_name(expr: ast.AST | None) -> str | None:
    """Return the fully qualified exception name referenced by ``expr``.

    Returns
    -------
    str | None
        Exception identifier when resolvable.
    """
    if expr is None:
        return None
    if isinstance(expr, ast.Call):
        return _exception_name(expr.func)
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        parts: list[str] = []
        current: ast.AST | None = expr
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        if parts:
            return ".".join(reversed(parts))
    return None


def collect_function_raises(tree: ast.Module) -> dict[str, list[str]]:
    """Map function names to the exceptions they raise.

    Returns
    -------
    dict[str, list[str]]
        Mapping of function names to sorted exception lists.
    """
    raises_map: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raised: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise):
                    name = _exception_name(sub.exc)
                    if name:
                        raised.add(name.split(".")[-1])
            if raised:
                raises_map[node.name] = raised
    return {name: sorted(values) for name, values in raises_map.items()}


def _extract_dunder_all(tree: ast.Module) -> list[str] | None:
    """Extract ``__all__`` assignments when present.

    Parameters
    ----------
    tree : ast.Module
        Parsed module whose ``__all__`` definition should be inspected.

    Returns
    -------
    list[str] | None
        List of exported symbols if ``__all__`` is defined, otherwise None.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    return [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
    return None


def collect_docstats(tree: ast.Module) -> DocStats:
    """Compute docstring coverage counts for modules, classes, and functions.

    Parameters
    ----------
    tree : ast.Module
        Parsed module tree.

    Returns
    -------
    DocStats
        Coverage counters ready for serialization.
    """
    module_doc = bool(ast.get_docstring(tree))
    class_total = class_with = func_total = func_with = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_total += 1
            if ast.get_docstring(node):
                class_with += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_total += 1
            if ast.get_docstring(node):
                func_with += 1
    return DocStats(module_doc, class_total, class_with, func_total, func_with)


def collect_typehints(tree: ast.Module) -> TypeHintStats:
    """Summarize how thoroughly a module annotates its functions.

    Parameters
    ----------
    tree : ast.Module
        Parsed module tree.

    Returns
    -------
    TypeHintStats
        Aggregated counts for annotated returns and parameters.
    """
    functions = annotated_returns = total_params = annotated_params = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
            if node.returns is not None:
                annotated_returns += 1
            params = [
                *getattr(node.args, "posonlyargs", []),
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            if node.args.vararg:
                params.append(node.args.vararg)
            if node.args.kwarg:
                params.append(node.args.kwarg)
            for p in params:
                total_params += 1
                if getattr(p, "annotation", None) is not None:
                    annotated_params += 1
    return TypeHintStats(functions, annotated_returns, total_params, annotated_params)


def _max_nesting(node: ast.AST, depth: int = 0) -> int:
    """Return the deepest nested control structure within an AST subtree.

    Parameters
    ----------
    node : ast.AST
        Node whose descendants will be inspected.
    depth : int, optional
        Current recursion depth, by default 0.

    Returns
    -------
    int
        Maximum nesting depth discovered under ``node``.
    """
    # Count blocks that increase nesting levels
    inc = (
        ast.If,
        ast.For,
        ast.While,
        ast.With,
        ast.Try,
        ast.Match,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    maxd = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, inc):
            md = _max_nesting(child, depth + 1)
            maxd = max(maxd, md)
        else:
            md = _max_nesting(child, depth)
            maxd = max(maxd, md)
    return maxd


def collect_complexity(tree: ast.Module) -> ComplexityStats:
    """Compute branch-based complexity proxies from an AST tree.

    Parameters
    ----------
    tree : ast.Module
        Parsed module tree.

    Returns
    -------
    ComplexityStats
        Branch counts and maximum nesting depth for the module.
    """
    # Lightweight proxy for cyclomatic complexity:
    # count of branching nodes + boolean operators
    branch_nodes = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match)
    branch_points = 0
    for n in ast.walk(tree):
        if isinstance(n, branch_nodes):
            branch_points += 1
        elif isinstance(n, ast.BoolOp):
            # "a and b and c" has 2 decision points
            branch_points += max(0, len(getattr(n, "values", [])) - 1)
        elif isinstance(n, ast.ExceptHandler):
            branch_points += 1
    max_nesting = _max_nesting(tree, 0)
    return ComplexityStats(branch_points=branch_points, max_nesting=max_nesting)


def is_test_file(path: Path, modname: str) -> bool:
    """Heuristically determine whether a module represents a test file.

    Parameters
    ----------
    path : Path
        Filesystem path being analyzed.
    modname : str
        Dotted name returned by :func:`module_name_from_path`.

    Returns
    -------
    bool
        ``True`` when the path looks like a test module.
    """
    stem = path.stem
    mod_parts = modname.split(".")
    return (
        "tests" in path.parts
        or stem.startswith("test_")
        or stem.endswith("_test")
        or "tests" in mod_parts
    )


def analyze_file(
    scan_root: Path,
    path: Path,
    *,
    strip_prefixes: tuple[str, ...] = (),
    use_libcst: bool = False,
) -> ModuleReport:
    """Produce a :class:`ModuleReport` for a single source file.

    Parameters
    ----------
    scan_root : Path
        Root directory passed to the scanner.
    path : Path
        File to analyze.
    strip_prefixes : tuple[str, ...], optional
        Path components to drop when computing module names.
    use_libcst : bool, optional
        When ``True``, capture LibCST-derived import metadata for the module.

    Returns
    -------
    ModuleReport
        Structured metadata for downstream aggregation.
    """
    modname = module_name_from_path(scan_root, path, strip_prefixes=strip_prefixes)
    tree = safe_parse_ast(path)
    if tree is None:
        return ModuleReport(
            module=modname,
            path=str(path),
            is_test=is_test_file(path, modname),
            imports=[],
            public_api=[],
            doc=DocStats(
                module_doc=False,
                class_total=0,
                class_with_doc=0,
                func_total=0,
                func_with_doc=0,
            ),
            typing=TypeHintStats(
                functions=0,
                annotated_returns=0,
                total_params=0,
                annotated_params=0,
            ),
            complexity=ComplexityStats(branch_points=0, max_nesting=0),
            loc=file_loc(path),
            parse_ok=False,
            parse_error="parse_failed",
        )
    imports = collect_imports(modname, tree)
    public_api = collect_public_api(tree)
    public_api_details = collect_public_api_details(tree, path, set(public_api))
    doc = collect_docstats(tree)
    typing = collect_typehints(tree)
    complexity = collect_complexity(tree)
    raises_map = collect_function_raises(tree)
    imports_cst: dict[str, Any] | None = None
    if use_libcst:
        cst_report = collect_imports_with_libcst(path, modname)
        imports_cst = {
            "imports": list(cst_report.imports),
            "type_checking_imports": list(cst_report.tc_imports),
            "exports": list(cst_report.exports),
            "star_imports": list(cst_report.star_imports),
            "has_parse_errors": cst_report.has_parse_errors,
        }
    return ModuleReport(
        module=modname,
        path=str(path),
        is_test=is_test_file(path, modname),
        imports=imports,
        public_api=public_api,
        public_api_details=public_api_details,
        raises=raises_map,
        doc=doc,
        typing=typing,
        complexity=complexity,
        loc=file_loc(path),
        parse_ok=True,
        imports_cst=imports_cst,
    )


# --------------------------
# Test enrichment
# --------------------------


def collect_relevant_tests(config: TestScanConfig) -> list[ModuleReport]:
    """Scan test directories and keep only tests that target `target_modules`.

    Parameters
    ----------
    config : TestScanConfig
        Immutable settings describing how and where tests should be scanned.

    Returns
    -------
    list[ModuleReport]
        Reports for tests that exercise the selected modules.
    """
    results: list[ModuleReport] = []
    seen = set(config.exclude_paths)
    search_roots = config.tests_subdirs or ("tests",)
    for subdir in search_roots:
        candidate_root = (config.repo_root / subdir).resolve()
        if not candidate_root.exists():
            continue
        for path in iter_py_files(candidate_root):
            if str(path) in seen:
                continue
            report = analyze_file(
                config.repo_root,
                path,
                strip_prefixes=config.strip_prefixes,
                use_libcst=config.use_libcst,
            )
            if not report.is_test:
                continue
            if _imports_target_modules(report.imports, config.target_modules):
                results.append(report)
                seen.add(report.path)
    return results


def _imports_target_modules(imports: list[str], targets: set[str]) -> bool:
    """Return True when an import references any module in `targets`.

    Parameters
    ----------
    imports : list[str]
        Import targets recorded for a test module.
    targets : set[str]
        Module names included in the scan scope.

    Returns
    -------
    bool
        ``True`` when any import overlaps with the target modules.
    """
    if not targets:
        return False
    for imp in imports:
        if imp in targets:
            return True
        for target in targets:
            if target.startswith(f"{imp}.") or imp.startswith(f"{target}."):
                return True
    return False


# --------------------------
# Git metadata (single pass)
# --------------------------


@dataclass(frozen=True)
class GitMeta:
    """Git history metadata for a scanned path.

    Attributes
    ----------
    last_epoch : int
        UNIX timestamp of the most recent commit touching the file.
    last_author : str
        Author of the commit referenced by ``last_epoch``.
    """

    last_epoch: int
    last_author: str


def collect_git_meta(repo_root: Path, scope_paths: list[Path]) -> dict[str, GitMeta]:
    """Capture last-commit metadata for paths reachable from ``scope_paths``.

    Parameters
    ----------
    repo_root : Path
        Directory containing the Git repository.
    scope_paths : list[Path]
        Paths whose histories should be inspected.

    Returns
    -------
    dict[str, GitMeta]
        Mapping of absolute file paths to their ``GitMeta`` record.
    """
    meta: dict[str, GitMeta] = {}
    if shutil.which("git") is None or not scope_paths:
        return meta

    repo_root = repo_root.resolve()
    scope_roots = [path.resolve() for path in scope_paths]

    if not _is_git_repo(repo_root):
        return meta

    scope_arg = _git_scope_relative_path(repo_root, scope_roots)
    try:
        output = run_subprocess(
            [
                "git",
                "log",
                "--date-order",
                "--pretty=format:%ct\t%an",
                "--name-only",
                "--",
                scope_arg,
            ],
            cwd=repo_root,
            timeout=GIT_COMMAND_TIMEOUT,
        )
    except SubprocessError as exc:
        logger.debug("git log unavailable during repo scan", exc_info=exc)
        return meta

    return _parse_git_log_output(output, repo_root, scope_roots)


def _is_git_repo(repo_root: Path) -> bool:
    """Return True when the provided path resides inside a Git repository.

    Parameters
    ----------
    repo_root : Path
        Candidate repository root to validate.

    Returns
    -------
    bool
        True if path is inside a Git repository, False otherwise.
    """
    try:
        run_subprocess(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            timeout=GIT_COMMAND_TIMEOUT,
        )
    except SubprocessError:
        return False
    return True


def _git_scope_relative_path(repo_root: Path, scope_paths: Iterable[Path]) -> str:
    """Compute the relative path argument passed to git for limiting scope.

    Parameters
    ----------
    repo_root : Path
        Root directory of the Git repository.
    scope_paths : Iterable[Path]
        Paths whose common ancestor should constrain the log.

    Returns
    -------
    str
        Relative path string for git command, or "." if no common path exists.
    """
    resolved = [path.resolve() for path in scope_paths]
    if not resolved:
        return "."
    common = Path(os.path.commonpath([str(path) for path in resolved]))
    try:
        relative = common.relative_to(repo_root)
    except ValueError:
        return "."
    rel_str = str(relative)
    return rel_str if rel_str else "."


def _parse_git_log_output(
    output: str, repo_root: Path, scope_paths: Iterable[Path]
) -> dict[str, GitMeta]:
    """Transform ``git log`` output into ``GitMeta`` entries.

    Parameters
    ----------
    output : str
        Raw stdout captured from ``git log``.
    repo_root : Path
        Root directory used to resolve relative paths.
    scope_paths : Iterable[Path]
        Set of paths restricting which files should be recorded.

    Returns
    -------
    dict[str, GitMeta]
        Mapping from file paths to their Git metadata.
    """
    meta: dict[str, GitMeta] = {}
    current_epoch: int | None = None
    current_author: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "\t" in stripped:
            ts, author = stripped.split("\t", 1)
            if ts.isdigit():
                current_epoch = int(ts)
                current_author = author
            continue
        if current_epoch is None or current_author is None:
            continue
        file_path = (repo_root / stripped).resolve()
        if not _is_within_scope(file_path, scope_paths):
            continue
        key = str(file_path)
        meta.setdefault(key, GitMeta(last_epoch=current_epoch, last_author=current_author))
    return meta


def _is_within_scope(path: Path, scope_paths: Iterable[Path]) -> bool:
    """Check whether ``path`` lies inside one of the ``scope_paths``.

    Parameters
    ----------
    path : Path
        Candidate path to evaluate.
    scope_paths : Iterable[Path]
        Collection of allowed prefixes.

    Returns
    -------
    bool
        True if path is within scope, False otherwise.
    """
    for scope in scope_paths:
        try:
            path.relative_to(scope.resolve())
        except ValueError:
            continue
        else:
            return True
    return False


# --------------------------
# Graph + post-processing
# --------------------------


def build_local_import_graph(reports: list[ModuleReport]) -> list[tuple[str, str]]:
    """Construct a list of import edges referencing modules inside the scan.

    Parameters
    ----------
    reports : list[ModuleReport]
        Module metadata generated by :func:`analyze_file`.

    Returns
    -------
    list[tuple[str, str]]
        Sorted ``(source, target)`` edges within the scanned modules.
    """
    # Keep edges only between modules present in this scan
    name_to_mod = {r.module: r for r in reports if r.parse_ok}
    # Also allow imports to point to package prefixes that exist as modules
    available = set(name_to_mod.keys())
    edges: set[tuple[str, str]] = set()
    for r in reports:
        if not r.parse_ok:
            continue
        import_sources: Iterable[str] = r.imports
        if (
            r.imports_cst
            and not r.imports_cst.get("has_parse_errors")
            and r.imports_cst.get("imports")
        ):
            import_sources = r.imports_cst["imports"]
        for imp in import_sources:
            # normalize: keep full import, and also match prefixes
            # allow partial prefix mapping: "pkg.sub" -> match "pkg.sub" or "pkg.sub.x"
            for target in available:
                if target == imp or target.startswith(imp + "."):
                    if target == r.module:
                        continue
                    edges.add((r.module, target))
    return sorted(edges)


def map_tests_to_modules(reports: list[ModuleReport]) -> dict[str, list[str]]:
    """Associate modules with the tests that import them.

    Parameters
    ----------
    reports : list[ModuleReport]
        Module metadata generated during the scan.

    Returns
    -------
    dict[str, list[str]]
        Sorted mapping of module names to tests referencing them.
    """
    mods = {r.module for r in reports}
    tests = [r for r in reports if r.is_test and r.parse_ok]
    mapping: dict[str, set[str]] = {m: set() for m in mods}
    for t in tests:
        for imp in t.imports:
            for m in mods:
                if m == imp or m.startswith(imp + ".") or imp.startswith(m + "."):
                    mapping[m].add(t.module)
    # Drop empty entries
    return {m: sorted(v) for m, v in mapping.items() if v}


def _apply_test_metadata(
    reports: list[ModuleReport], test_map: dict[str, list[str]]
) -> list[ModuleReport]:
    """Attach test counts/flags to module reports.

    Returns
    -------
    list[ModuleReport]
        Reports updated with testing metadata.
    """
    counts = {module: len(tests) for module, tests in test_map.items()}
    updated: list[ModuleReport] = []
    for report in reports:
        if report.is_test:
            updated.append(report)
            continue
        count = counts.get(report.module, 0)
        updated.append(
            replace(
                report,
                test_count=count,
                has_tests=count > 0,
                public_api_without_tests=list(report.public_api) if count == 0 else [],
            )
        )
    return updated


def write_dot(edges: list[tuple[str, str]], out_path: Path) -> None:
    """Persist an import graph to a Graphviz DOT file.

    Parameters
    ----------
    edges : list[tuple[str, str]]
        Directed edges produced by :func:`build_local_import_graph`.
    out_path : Path
        Destination for the DOT file.
    """
    lines = ["digraph imports {"]
    for a, b in edges:
        lines.append(f'  "{a}" -> "{b}";')
    lines.append("}")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def summarize_graph(reports: list[ModuleReport], edges: list[tuple[str, str]]) -> dict[str, Any]:
    """Return graph analytics for downstream consumption.

    Returns
    -------
    dict[str, Any]
        Node metrics (degrees, PageRank, cycle membership) and cycle list.
    """
    nodes = {r.module: r.is_test for r in reports if r.parse_ok}
    if not nodes:
        return {"nodes": {}, "cycles": []}

    in_deg = dict.fromkeys(nodes.keys(), 0)
    out_deg = dict.fromkeys(nodes.keys(), 0)
    filtered_edges: list[tuple[str, str]] = []
    for src, dst in edges:
        if src in nodes and dst in nodes:
            out_deg[src] += 1
            in_deg[dst] += 1
            filtered_edges.append((src, dst))

    cycles = _strongly_connected_components(nodes.keys(), filtered_edges)
    cycle_nodes = {entry for comp in cycles for entry in comp}
    ranks = _pagerank(nodes.keys(), filtered_edges)

    node_info = {
        node: {
            "in_degree": in_deg[node],
            "out_degree": out_deg[node],
            "pagerank": round(ranks.get(node, 0.0), 6),
            "cycle": node in cycle_nodes,
            "is_test": is_test,
        }
        for node, is_test in nodes.items()
    }
    return {"nodes": node_info, "cycles": cycles}


def _strongly_connected_components(
    nodes: Iterable[str], edges: list[tuple[str, str]]
) -> list[list[str]]:
    """Compute strongly connected components using Kosaraju's algorithm.

    Returns
    -------
    list[list[str]]
        Each entry is a strongly connected component with >1 node.
    """
    node_list = list(nodes)
    graph: dict[str, list[str]] = {}
    reverse_graph: dict[str, list[str]] = {}
    for node in node_list:
        graph[node] = []
        reverse_graph[node] = []
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        reverse_graph.setdefault(dst, []).append(src)

    order = _dfs_finish_order(graph)
    seen: set[str] = set()
    components: list[list[str]] = []
    for node in reversed(order):
        if node in seen:
            continue
        comp = _collect_component(reverse_graph, node, seen)
        if len(comp) > 1:
            components.append(comp)
    return components


def _dfs_finish_order(graph: dict[str, list[str]]) -> list[str]:
    """Return nodes ordered by DFS finish time.

    Returns
    -------
    list[str]
        Nodes ordered by decreasing finish time.
    """
    seen: set[str] = set()
    order: list[str] = []

    def dfs(node: str) -> None:
        seen.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in seen:
                dfs(neighbor)
        order.append(node)

    for node in graph:
        if node not in seen:
            dfs(node)
    return order


def _collect_component(
    reverse_graph: dict[str, list[str]],
    start: str,
    seen: set[str],
) -> list[str]:
    """Collect nodes reachable in the reverse graph from ``start``.

    Returns
    -------
    list[str]
        Nodes forming a single strongly connected component.
    """
    component: list[str] = []
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        component.append(node)
        stack.extend(neighbor for neighbor in reverse_graph.get(node, []) if neighbor not in seen)
    return component


def _pagerank(
    nodes: Iterable[str], edges: list[tuple[str, str]], damping: float = 0.85, iters: int = 25
) -> dict[str, float]:
    """Compute a simple PageRank over the provided nodes.

    Returns
    -------
    dict[str, float]
        PageRank scores keyed by node.
    """
    node_list = list(nodes)
    if not node_list:
        return {}
    score = {node: 1.0 / len(node_list) for node in node_list}
    outgoing: dict[str, list[str]] = {}
    for node in node_list:
        outgoing[node] = []
    for src, dst in edges:
        outgoing.setdefault(src, []).append(dst)
    base = (1.0 - damping) / len(node_list)
    for _ in range(iters):
        next_score = dict.fromkeys(node_list, base)
        for node in node_list:
            neighbors = outgoing.get(node) or []
            if not neighbors:
                continue
            share = score[node] / len(neighbors)
            for neighbor in neighbors:
                next_score[neighbor] = next_score.get(neighbor, base) + damping * share
        score = next_score
    return score


def write_enriched_dot(
    edges: list[tuple[str, str]],
    out_path: Path,
    summary: dict[str, Any],
) -> None:
    """Write a DOT file with node styling based on analytics."""
    nodes = summary.get("nodes", {})
    lines = ["digraph imports {"]
    for node, info in nodes.items():
        attrs = []
        if info.get("is_test"):
            attrs.append('style="dashed"')
        color = "red" if info.get("cycle") else "black"
        attrs.append(f'color="{color}"')
        pagerank = info.get("pagerank", 0.0) or 0.0
        penwidth = 1.0 + pagerank * 40
        attrs.append(f'penwidth="{penwidth:.2f}"')
        lines.append(f'  "{node}" [{", ".join(attrs)}];')
    for src, dst in edges:
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------
# CLI
# --------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser for the CLI.

    Returns
    -------
    argparse.ArgumentParser
        Parser pre-populated with all CLI arguments.
    """
    ap = argparse.ArgumentParser(description="Scan a folder and emit repo metrics (stdlib-only).")
    ap.add_argument(
        "folder",
        nargs="?",
        default=".",
        type=str,
        help="Folder to scan (defaults to current working directory)",
    )
    ap.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Git repo root (defaults to nearest parent of folder)",
    )
    ap.add_argument("--out-json", type=str, default="repo_metrics.json")
    ap.add_argument("--out-dot", type=str, default="import_graph.dot")
    ap.add_argument(
        "--strip-prefix",
        action="append",
        default=["src"],
        help="Top-level path prefixes to drop from module names (default: %(default)s)",
    )
    ap.add_argument(
        "--include-subdir",
        action="append",
        default=None,
        help=(
            "Relative subdirectories to include during scanning; "
            "can be provided multiple times (defaults to all subdirs)."
        ),
    )
    ap.add_argument(
        "--tests-subdir",
        action="append",
        default=None,
        help=(
            "Relative test directories to scan for relevant files "
            "(default: %(default)s when unset)."
        ),
    )
    ap.add_argument(
        "--include-tests",
        dest="include_tests",
        action="store_true",
        default=True,
        help="Automatically include tests that exercise the selected modules.",
    )
    ap.add_argument(
        "--no-include-tests",
        dest="include_tests",
        action="store_false",
        help="Disable automatic inclusion of relevant test files.",
    )
    ap.set_defaults(with_libcst=True, with_griffe=True, write_enriched_dot=True)
    ap.add_argument(
        "--no-libcst",
        dest="with_libcst",
        action="store_false",
        help="Disable LibCST enrichment (enabled by default).",
    )
    ap.add_argument(
        "--no-griffe",
        dest="with_griffe",
        action="store_false",
        help="Disable Griffe-powered API/doc extraction.",
    )
    ap.add_argument(
        "--docstyle",
        choices=["google", "numpy", "sphinx"],
        default="google",
        help="Docstring style passed to Griffe parsing (default: %(default)s).",
    )
    ap.add_argument(
        "--enriched-dot",
        type=str,
        default="import_graph_enriched.dot",
        help="Path for an analytics-enriched DOT graph (default: %(default)s).",
    )
    ap.add_argument(
        "--no-enriched-dot",
        dest="write_enriched_dot",
        action="store_false",
        help="Skip writing the analytics-enriched DOT graph.",
    )
    return ap


def _collect_module_reports(
    scan_root: Path,
    *,
    include_subdirs: tuple[str, ...],
    strip_prefixes: tuple[str, ...],
    use_libcst: bool,
) -> list[ModuleReport]:
    """Collect module reports for all Python files under ``scan_root``.

    Extended Summary
    ----------------
    Scans the filesystem for Python source files and analyzes each one
    to extract import edges, public APIs, docstring coverage, typing
    coverage, and complexity metrics. This is the core data collection
    step of the repository scanning workflow. Results are used to build
    the JSON payload and import graph visualization.

    Parameters
    ----------
    scan_root : Path
        Root directory to scan recursively. Must exist and be readable.
        Python files are discovered via `iter_py_files()`.
    include_subdirs : tuple[str, ...]
        Relative subdirectory names to include in the scan (e.g., ("src", "tests")).
        Empty tuple means scan all subdirectories. Used to filter
        `iter_py_files()` output.
    strip_prefixes : tuple[str, ...]
        Module name prefixes to strip when computing module identifiers
        (e.g., ("src.",) to convert "src.kgfoundry.foo" to "kgfoundry.foo").
        Applied during `analyze_file()` processing.
    use_libcst : bool
        If True, use LibCST for enhanced import analysis (type-checking
        imports, star imports). If False, use AST-only parsing.
        Affects `analyze_file()` behavior and import edge extraction.

    Returns
    -------
    list[ModuleReport]
        Per-module metadata discovered during scanning. Each report
        contains module name, import edges, parse status, docstring
        coverage, typing coverage, complexity metrics, and test mapping.
        Order matches filesystem traversal order (not sorted).

    Notes
    -----
    Time O(n * m) where n is number of files and m is average file size.
    Memory O(n) for the report list. No I/O beyond file reads.
    This function is the bottleneck of the scanning workflow; consider
    parallelization for large repositories.

    See Also
    --------
    iter_py_files : File discovery utility
    analyze_file : Per-file analysis function
    ModuleReport : Report dataclass structure
    """
    return [
        analyze_file(
            scan_root,
            path,
            strip_prefixes=strip_prefixes,
            use_libcst=use_libcst,
        )
        for path in iter_py_files(scan_root, include_subdirs=include_subdirs)
    ]


def _collect_api_symbols_for_payload(
    module_roots: set[str],
    *,
    options: PayloadOptions,
) -> list[dict[str, Any]]:
    """Return serialized API symbols when Griffe integration is enabled.

    Extended Summary
    ----------------
    Collects public API symbols (classes, functions, constants) using
    Griffe's AST-based analysis when `with_griffe` is enabled in options.
    This provides richer symbol metadata (docstrings, signatures, decorators)
    than the basic AST parsing used in `analyze_file()`. Symbols are
    serialized to dictionaries for JSON payload inclusion.

    Parameters
    ----------
    module_roots : set[str]
        Top-level module names discovered during scanning (e.g., {"kgfoundry", "tools"}).
        Used to filter Griffe analysis to relevant packages. Empty set
        results in empty return value.
    options : PayloadOptions
        Configuration object containing `scan_root`, `with_griffe` flag,
        and `docstyle` preference. The `with_griffe` flag must be True
        for this function to perform any work.

    Returns
    -------
    list[dict[str, Any]]
        Serialized dataclass entries describing public symbols. Each
        dictionary contains symbol name, kind (class/function/constant),
        module path, docstring, signature (if applicable), and metadata.
        Empty list if `with_griffe` is False or `module_roots` is empty.

    Notes
    -----
    Time O(p * f) where p is number of packages and f is average files per package.
    Memory O(s) where s is number of symbols. No I/O beyond file reads.
    This function is a no-op if `options.with_griffe` is False, returning
    an empty list immediately.

    See Also
    --------
    collect_api_symbols_with_griffe : Griffe-based symbol collection
    PayloadOptions : Configuration dataclass
    """
    if not options.with_griffe:
        return []
    package_names = sorted(root for root in module_roots if root)
    if not package_names:
        return []
    return [
        asdict(symbol)
        for symbol in collect_api_symbols_with_griffe(
            options.scan_root, package_names, docstyle=options.docstyle
        )
    ]


def _derive_external_dependencies(
    reports: list[ModuleReport],
    module_roots: set[str],
    *,
    with_libcst: bool,
) -> list[str]:
    """Compute external dependency roots based on LibCST data.

    Extended Summary
    ----------------
    Analyzes import statements across all scanned modules to identify
    external dependencies (packages not in `module_roots`). Uses LibCST
    import data when available to capture type-checking imports and
    star imports that AST-only parsing misses. Returns the top-level
    package names (first component of import paths) for dependency
    tracking and visualization.

    Parameters
    ----------
    reports : list[ModuleReport]
        Module reports from `_collect_module_reports()`. Each report
        contains import lists and optional LibCST import metadata.
        Used to extract import names and compute dependency roots.
    module_roots : set[str]
        Top-level module names that are part of the scanned codebase
        (e.g., {"kgfoundry", "tools"}). Imports matching these roots
        are excluded from external dependencies.
    with_libcst : bool
        If True, use LibCST import data (`imports_cst` field) to
        include type-checking imports and star imports. If False,
        returns empty list immediately.

    Returns
    -------
    list[str]
        Sorted list of dependency roots detected in the scan. Each
        string is the top-level package name (e.g., "numpy", "fastapi").
        Empty list if `with_libcst` is False or no external dependencies
        are found.

    Notes
    -----
    Time O(n * i) where n is number of reports and i is average imports per module.
    Memory O(d) where d is number of unique dependency roots. No I/O.
    This function is a no-op if `with_libcst` is False, returning an
    empty list immediately.

    See Also
    --------
    ModuleReport : Report structure with import data
    _collect_module_reports : Report collection function
    """
    if not with_libcst:
        return []
    deps: set[str] = set()
    for report in reports:
        for name in report.imports:
            root = name.split(".", 1)[0] if name else ""
            if root and root not in module_roots:
                deps.add(root)
        if not report.imports_cst:
            continue
        for name in report.imports_cst.get("type_checking_imports", []):
            root = name.split(".", 1)[0] if name else ""
            if root and root not in module_roots:
                deps.add(root)
        for name in report.imports_cst.get("star_imports", []):
            root = name.split(".", 1)[0] if name else ""
            if root and root not in module_roots:
                deps.add(root)
    return sorted(deps)


def _assemble_payload(
    *,
    reports: list[ModuleReport],
    edges: list[tuple[str, str]],
    graph_summary: dict[str, Any],
    options: PayloadOptions,
) -> dict[str, Any]:
    """Compose the JSON payload written to disk.

    Extended Summary
    ----------------
    Assembles the complete JSON payload structure from collected module
    reports, import edges, test mappings, git metadata, API symbols, and
    external dependencies. This payload is the canonical output format
    for repository scanning, consumed by documentation generators, CI
    automation, and dependency analysis tools. The structure follows
    the Agent Operating Protocol (AOP) specifications.

    Parameters
    ----------
    reports : list[ModuleReport]
        Module reports from `_collect_module_reports()`. Serialized
        to the "modules" array in the payload. Used to compute summary
        statistics (file count, parse success rate, test count).
    edges : list[tuple[str, str]]
        Import edge tuples (source_module, target_module) extracted
        during scanning. Included as "import_edges" in the payload
        for graph visualization and dependency analysis.
    graph_summary : dict[str, Any]
        Derived graph analytics (degrees, PageRank, strongly connected
        components) stored under "graph_summary".
    options : PayloadOptions
        Configuration object containing `scan_root`, `repo_root`,
        `with_griffe`, `with_libcst`, and `docstyle`. Used to derive
        module roots, trigger API symbol collection, and compute
        external dependencies.

    Returns
    -------
    dict[str, Any]
        Payload ready to be serialized as JSON. Contains keys:
        "generated_at" (ISO timestamp), "scan_root", "repo_root",
        "summary" (file/test/parse stats), "modules" (serialized reports),
        "import_edges", "tests_to_modules" (test mapping), "git" (metadata),
        "api_symbols" (if Griffe enabled), "external_deps" (if LibCST enabled),
        and "graph_summary" describing import-graph analytics.

    Notes
    -----
    Time O(n + m + s) where n is reports, m is edges, s is symbols.
    Memory O(n + m + s) for the payload dictionary. No I/O beyond
    git metadata collection. The payload structure is stable and
    versioned per AOP specifications.

    See Also
    --------
    _collect_module_reports : Report collection
    _collect_api_symbols_for_payload : API symbol collection
    _derive_external_dependencies : Dependency extraction
    map_tests_to_modules : Test mapping utility
    collect_git_meta : Git metadata collection
    """
    test_map = map_tests_to_modules(reports)
    git_meta = collect_git_meta(options.repo_root, [options.scan_root])
    git_by_path = {k: asdict(v) for k, v in git_meta.items()}
    module_roots = {r.module.split(".", 1)[0] for r in reports if r.module}
    api_symbols_payload = _collect_api_symbols_for_payload(module_roots, options=options)
    external_deps = _derive_external_dependencies(
        reports,
        module_roots,
        with_libcst=options.with_libcst,
    )

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scan_root": str(options.scan_root),
        "repo_root": str(options.repo_root),
        "summary": {
            "files": len(reports),
            "parsed_ok": sum(1 for r in reports if r.parse_ok),
            "tests": sum(1 for r in reports if r.is_test),
        },
        "modules": [asdict(r) for r in reports],
        "import_edges": edges,
        "tests_to_modules": test_map,
        "git": git_by_path,
        "api_symbols": api_symbols_payload,
        "external_deps": external_deps,
        "graph_summary": graph_summary,
    }


def _execute_scan(args: argparse.Namespace) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Run the scanning workflow and return the payload plus import edges.

    Extended Summary
    ----------------
    Orchestrates the complete repository scanning workflow: validates
    scan root, collects module reports, extracts import edges, assembles
    the JSON payload, and optionally writes outputs to disk. This is the
    main entry point for the scanning process, called by the CLI after
    argument parsing. Returns the payload and edges for programmatic
    use or further processing.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing scan configuration:
        `folder` (scan root path), `repo_root` (optional, defaults to
        scan root), `strip_prefix` (module prefix stripping), `include_subdir`
        (subdirectory filtering), `with_griffe` (Griffe integration),
        `with_libcst` (LibCST integration), `docstyle` (docstring style),
        `out_json` (optional JSON output path), `out_dot` (optional DOT
        output path).

    Returns
    -------
    tuple[dict[str, Any], list[tuple[str, str]]]
        JSON payload (sans DOT output) and the import edge list.
        The payload is the complete scan result structure; edges are
        the (source, target) import tuples extracted during scanning.
        Both can be used for programmatic analysis or written to disk
        via the `out_json` and `out_dot` arguments.

    Notes
    -----
    Time dominated by `_collect_module_reports()` (O(n * m) file analysis).
    Memory O(n + m + s) for reports, edges, and payload. I/O includes
    file reads during scanning and optional JSON/DOT writes. This function
    is the main workflow coordinator; performance is determined by the
    scanning and analysis steps.

    Calls `sys.exit(2)` (raising `SystemExit`) if `args.folder` does not
    exist or is not a directory. This is a fail-fast validation before
    starting the scan.

    See Also
    --------
    _collect_module_reports : Module report collection
    _assemble_payload : Payload assembly
    extract_import_edges : Import edge extraction
    """
    scan_root = Path(args.folder).resolve()
    if not scan_root.exists() or not scan_root.is_dir():
        msg = f"scan root not found or not a directory: {scan_root}"
        logger.error(msg)
        sys.stderr.write(f"{msg}\n")
        sys.exit(2)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else scan_root
    strip_prefixes = tuple(args.strip_prefix)
    include_subdirs = tuple(args.include_subdir or [])
    reports = _collect_module_reports(
        scan_root,
        include_subdirs=include_subdirs,
        strip_prefixes=strip_prefixes,
        use_libcst=args.with_libcst,
    )

    if args.include_tests:
        reports.extend(
            collect_relevant_tests(
                TestScanConfig(
                    repo_root=repo_root,
                    tests_subdirs=tuple(args.tests_subdir or ("tests",)),
                    strip_prefixes=strip_prefixes,
                    target_modules={r.module for r in reports if not r.is_test},
                    exclude_paths={r.path for r in reports},
                    use_libcst=args.with_libcst,
                )
            )
        )

    edges = build_local_import_graph(reports)
    test_map = map_tests_to_modules(reports)
    reports = _apply_test_metadata(reports, test_map)
    graph_summary = summarize_graph(reports, edges)
    payload = _assemble_payload(
        reports=reports,
        edges=edges,
        graph_summary=graph_summary,
        options=PayloadOptions(
            scan_root=scan_root,
            repo_root=repo_root,
            with_griffe=args.with_griffe,
            with_libcst=args.with_libcst,
            docstyle=cast("DocstringStyle", args.docstyle),
        ),
    )

    return payload, edges


def main() -> None:
    """Entrypoint for the CLI invocation defined in the module docstring.

    The function exits the process with ``sys.exit`` codes on failure.
    """
    args = _build_arg_parser().parse_args()
    payload, edges = _execute_scan(args)

    Path(args.out_json).write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    write_dot(edges, Path(args.out_dot))
    if getattr(args, "write_enriched_dot", False):
        write_enriched_dot(
            edges,
            Path(args.enriched_dot),
            payload.get("graph_summary", {}),
        )

    logger.info("Wrote %s and %s", args.out_json, args.out_dot)


if __name__ == "__main__":
    main()
