#!/usr/bin/env python3
# tools/repo_scan.py
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

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

# --------------------------
# utils
# --------------------------


def iter_py_files(root: Path) -> Iterator[Path]:
    root = root.resolve()
    for p in root.rglob("*.py"):
        try:
            rel = p.relative_to(root)
        except Exception:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p


def module_name_from_path(scan_root: Path, path: Path) -> str:
    rel = path.resolve().relative_to(scan_root.resolve())
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts).replace(os.sep, ".")


def safe_parse_ast(path: Path) -> ast.AST | None:
    try:
        with tokenize.open(path) as f:
            src = f.read()
        return ast.parse(src, filename=str(path))
    except Exception:
        return None


def file_loc(path: Path) -> int:
    try:
        with Path(path).open("rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


# --------------------------
# AST analyses
# --------------------------


@dataclass
class DocStats:
    module_doc: bool
    class_total: int
    class_with_doc: int
    func_total: int
    func_with_doc: int


@dataclass
class TypeHintStats:
    functions: int
    annotated_returns: int
    total_params: int
    annotated_params: int


@dataclass
class ComplexityStats:
    branch_points: int
    max_nesting: int


@dataclass
class ModuleReport:
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


def collect_imports(modname: str, tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)  # e.g. "package.sub"
        elif isinstance(node, ast.ImportFrom):
            # Handle relative imports: from .foo import bar
            level = getattr(node, "level", 0) or 0
            base = node.module or ""
            if level > 0:
                parts = modname.split(".")
                base_parts = parts[:-level] if level <= len(parts) else []
                base = ".".join([*base_parts, *([base] if base else [])])
            if base:
                imports.append(base)
    # Deduplicate, preserve order
    seen = set()
    out = []
    for imp in imports:
        if imp not in seen:
            seen.add(imp)
            out.append(imp)
    return out


def collect_public_api(tree: ast.AST) -> list[str]:
    # Respect __all__ = ["a", "b"] if present
    explicit: list[str] | None = None
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            vals = []
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    vals.append(elt.value)
                            explicit = vals
                    except Exception:
                        pass
    if explicit is not None:
        return explicit
    # Fallback: all top-level defs not starting with underscore
    names: list[str] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


def collect_docstats(tree: ast.AST) -> DocStats:
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


def collect_typehints(tree: ast.AST) -> TypeHintStats:
    functions = annotated_returns = total_params = annotated_params = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
            if node.returns is not None:
                annotated_returns += 1
            params = []
            params.extend(getattr(node.args, "posonlyargs", []))
            params.extend(node.args.args)
            params.extend(node.args.kwonlyargs)
            if node.args.vararg:
                params.append(node.args.vararg)
            if node.args.kwarg:
                params.append(node.args.kwarg)
            for p in params:
                total_params += 1
                if getattr(p, "annotation", None) is not None:
                    annotated_params += 1
    return TypeHintStats(functions, annotated_returns, total_params, annotated_params)


def _max_nesting(node: ast.AST, depth=0) -> int:
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
    current = depth
    maxd = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, inc):
            md = _max_nesting(child, depth + 1)
            maxd = max(maxd, md)
        else:
            md = _max_nesting(child, depth)
            maxd = max(maxd, md)
    return maxd


def collect_complexity(tree: ast.AST) -> ComplexityStats:
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
    stem = path.stem
    return ("tests" in path.parts) or stem.startswith("test_") or stem.endswith("_test")


def analyze_file(scan_root: Path, path: Path) -> ModuleReport:
    modname = module_name_from_path(scan_root, path)
    tree = safe_parse_ast(path)
    if tree is None:
        return ModuleReport(
            module=modname,
            path=str(path),
            is_test=is_test_file(path, modname),
            imports=[],
            public_api=[],
            doc=DocStats(False, 0, 0, 0, 0),
            typing=TypeHintStats(0, 0, 0, 0),
            complexity=ComplexityStats(0, 0),
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


@dataclass
class GitMeta:
    last_epoch: int
    last_author: str


def collect_git_meta(repo_root: Path, scope_paths: list[Path]) -> dict[str, GitMeta]:
    meta: dict[str, GitMeta] = {}
    if shutil.which("git") is None:
        return meta
    try:
        # make sure we're inside a git repo
        ok = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if ok.returncode != 0:
            return meta
        # one pass over history touching the folder; most recent wins (we iterate in date order)
        rel_folders = sorted({str(p.relative_to(repo_root)) for p in scope_paths})
        # Use the top-most directories once; passing too many args can exceed CLI limits
        # Strategy: ask git for the scope root once.
        top = os.path.commonpath([str(p) for p in scope_paths]) if scope_paths else "."
        cmd = [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--date-order",
            "--pretty=format:%ct\t%an",
            "--name-only",
            "--",
            top,
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if out.returncode != 0:
            return meta
        current_epoch = None
        current_author = None
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            if "\t" in line and re.match(r"^\d+\t", line):
                # header line
                ts, author = line.split("\t", 1)
                current_epoch = int(ts)
                current_author = author
            else:
                # file path
                if current_epoch is None or current_author is None:
                    continue
                fpath = (repo_root / line).resolve()
                if not any(str(fpath).startswith(str(p.resolve())) for p in scope_paths):
                    continue
                key = str(fpath)
                if key not in meta:
                    meta[key] = GitMeta(current_epoch, current_author)
    except Exception:
        pass
    return meta


# --------------------------
# Graph + post-processing
# --------------------------


def build_local_import_graph(reports: list[ModuleReport]) -> list[tuple[str, str]]:
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
            candidates = {imp}
            # allow partial prefix mapping: "pkg.sub" -> match "pkg.sub" or "pkg.sub.x"
            for target in available:
                if target == imp or target.startswith(imp + "."):
                    edges.add((r.module, target))
    return sorted(edges)


def map_tests_to_modules(reports: list[ModuleReport]) -> dict[str, list[str]]:
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
    lines = ["digraph imports {"]
    for a, b in edges:
        lines.append(f'  "{a}" -> "{b}";')
    lines.append("}")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------
# CLI
# --------------------------


def main() -> None:
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
        "generated_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()
        ),
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
