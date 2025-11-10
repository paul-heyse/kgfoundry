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

    python tools/repo_scan.py src --repo-root . \
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
from dataclasses import asdict, dataclass
from pathlib import Path

from kgfoundry_common.subprocess_utils import SubprocessError, run_subprocess

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


def iter_py_files(root: Path) -> Iterator[Path]:
    """Yield Python source files while skipping generated directories.

    Parameters
    ----------
    root : Path
        Root directory to traverse recursively.

    Yields
    ------
    Path
        Absolute paths to ``*.py`` files that are not inside ``SKIP_DIRS``.
    """
    root = root.resolve()
    for p in root.rglob("*.py"):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p


def module_name_from_path(scan_root: Path, path: Path) -> str:
    """Convert a filesystem path under ``scan_root`` into a dotted module path.

    Parameters
    ----------
    scan_root : Path
        Directory that anchors the module tree.
    path : Path
        Actual file path discovered while scanning.

    Returns
    -------
    str
        Dotted module path (``package.module``) relative to ``scan_root``.
    """
    rel = path.resolve().relative_to(scan_root.resolve())
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts).replace(os.sep, ".")


def safe_parse_ast(path: Path) -> ast.Module | None:
    """Parse a Python file into an AST, swallowing syntax errors gracefully.

    Parameters
    ----------
    path : Path
        Source file to parse.

    Returns
    -------
    ast.Module or None
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
    except Exception:
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
            base = _resolve_import_from_base(modname, node)
            if base:
                imports.append(base)
    return _dedupe_preserve_order(imports)


def _resolve_import_from_base(module_name: str, node: ast.ImportFrom) -> str | None:
    """Resolve the canonical import target for a ``from ... import`` statement.

    Returns
    -------
    str | None
        Resolved import target, or None if resolution fails.
    """
    module = node.module or ""
    level = getattr(node, "level", 0) or 0
    if level == 0:
        return module or None
    current_parts = module_name.split(".")
    base_parts = current_parts[:-level] if level <= len(current_parts) else []
    if module:
        base_parts.append(module)
    candidate = ".".join(part for part in base_parts if part)
    return candidate or None


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Return the unique values from ``items`` while preserving order.

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


def _extract_dunder_all(tree: ast.Module) -> list[str] | None:
    """Extract ``__all__`` assignments when present.

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


def analyze_file(scan_root: Path, path: Path) -> ModuleReport:
    """Produce a :class:`ModuleReport` for a single source file.

    Parameters
    ----------
    scan_root : Path
        Root directory passed to the scanner.
    path : Path
        File to analyze.

    Returns
    -------
    ModuleReport
        Structured metadata for downstream aggregation.
    """
    modname = module_name_from_path(scan_root, path)
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
    doc = collect_docstats(tree)
    typing = collect_typehints(tree)
    complexity = collect_complexity(tree)
    return ModuleReport(
        module=modname,
        path=str(path),
        is_test=is_test_file(path, modname),
        imports=imports,
        public_api=public_api,
        doc=doc,
        typing=typing,
        complexity=complexity,
        loc=file_loc(path),
        parse_ok=True,
    )


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
        for imp in r.imports:
            # normalize: keep full import, and also match prefixes
            # allow partial prefix mapping: "pkg.sub" -> match "pkg.sub" or "pkg.sub.x"
            for target in available:
                if target == imp or target.startswith(imp + "."):
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


# --------------------------
# CLI
# --------------------------


def main() -> None:
    """Entrypoint for the CLI invocation defined in the module docstring.

    The function exits the process with ``sys.exit`` codes on failure.
    """
    ap = argparse.ArgumentParser(description="Scan a folder and emit repo metrics (stdlib-only).")
    ap.add_argument("folder", type=str, help="Folder to scan (e.g., src/ or package root)")
    ap.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Git repo root (defaults to nearest parent of folder)",
    )
    ap.add_argument("--out-json", type=str, default="repo_metrics.json")
    ap.add_argument("--out-dot", type=str, default="import_graph.dot")
    args = ap.parse_args()

    scan_root = Path(args.folder).resolve()
    if not scan_root.exists() or not scan_root.is_dir():
        print(f"scan root not found or not a directory: {scan_root}", file=sys.stderr)
        sys.exit(2)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else scan_root
    reports: list[ModuleReport] = []
    paths: list[Path] = []

    for path in iter_py_files(scan_root):
        paths.append(path)
        reports.append(analyze_file(scan_root, path))

    edges = build_local_import_graph(reports)
    test_map = map_tests_to_modules(reports)

    git_meta = collect_git_meta(repo_root, [scan_root])
    git_by_path = {k: asdict(v) for k, v in git_meta.items()}

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scan_root": str(scan_root),
        "repo_root": str(repo_root),
        "summary": {
            "files": len(reports),
            "parsed_ok": sum(1 for r in reports if r.parse_ok),
            "tests": sum(1 for r in reports if r.is_test),
        },
        "modules": [asdict(r) for r in reports],
        "import_edges": edges,
        "tests_to_modules": test_map,
        "git": git_by_path,
    }

    Path(args.out_json).write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    write_dot(edges, Path(args.out_dot))

    print(f"Wrote {args.out_json} and {args.out_dot}")


if __name__ == "__main__":
    main()
