"""Completeness validation for modules.jsonl outputs."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import libcst as cst

from codeintel_rev.enrich.libcst_bridge import analyze_module
from codeintel_rev.enrich.types import ImportEdge, ModuleAnalysis

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    """Machine-readable completeness results."""

    missing_modules: list[str]
    extra_modules: list[str]
    unresolved_local_imports: list[tuple[str, str, str]]
    invalid_relative_imports: list[tuple[str, str, str]]
    missing_package_inits: list[str]
    impacts: Mapping[str, list[str]]


def report_completeness(repo_root: Path, modules_jsonl: Path) -> CompletenessReport:
    """Return a completeness snapshot for ``modules_jsonl`` relative to ``repo_root``.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    modules_jsonl : Path
        Path to the modules JSONL file to analyze.

    Returns
    -------
    CompletenessReport
        Structured report describing missing/extra modules and related issues.
    """
    analyses = _collect_module_analyses(repo_root)
    expected = set(analyses)
    observed = _load_modules_jsonl(modules_jsonl)
    missing_modules = sorted(expected - observed)
    extra_modules = sorted(observed - expected)

    edges = _collect_import_edges(analyses)
    invalid_relatives: list[tuple[str, str, str]] = []
    unresolved_locals: list[tuple[str, str, str]] = []
    impacts: dict[str, list[str]] = {}

    for module, analysis in analyses.items():
        for edge in analysis.imports:
            if _relative_out_of_bounds(module, edge):
                invalid_relatives.append((module, edge.dst_module, "relative_import_out_of_bounds"))
                impacts.setdefault(module, _downstream_impact(edges, module))
                continue
            if not _is_local_module(repo_root, edge.dst_module):
                if "." not in (edge.dst_module or ""):
                    continue
                unresolved_locals.append((module, edge.dst_module, "dangling_local_import"))
                impacts.setdefault(module, _downstream_impact(edges, module))

    missing_inits = sorted(
        str(path.relative_to(repo_root)) for path in _missing_inits(repo_root)
    )

    return CompletenessReport(
        missing_modules=missing_modules,
        extra_modules=extra_modules,
        unresolved_local_imports=sorted(unresolved_locals),
        invalid_relative_imports=sorted(invalid_relatives),
        missing_package_inits=missing_inits,
        impacts=impacts,
    )


def write_report(path: Path, report: CompletenessReport) -> None:
    """Persist ``report`` to ``path`` as JSON."""
    payload = {
        "missing_modules": report.missing_modules,
        "extra_modules": report.extra_modules,
        "unresolved_local_imports": report.unresolved_local_imports,
        "invalid_relative_imports": report.invalid_relative_imports,
        "missing_package_inits": report.missing_package_inits,
        "impacts": report.impacts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _collect_module_analyses(root: Path) -> dict[str, ModuleAnalysis]:
    analyses: dict[str, ModuleAnalysis] = {}
    for file_path in _iter_py_files(root):
        module = _module_name_for(root, file_path)
        try:
            analysis = analyze_module(root, file_path)
        except (OSError, ValueError, cst.ParserSyntaxError) as exc:  # pragma: no cover - defensive
            LOGGER.warning("Failed to analyze %s: %s", file_path, exc)
            continue
        analyses[module] = analysis
    return analyses


def _iter_py_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for candidate in root.rglob("*.py"):
        rel_parts = candidate.relative_to(root).parts
        if ".venv" in rel_parts or "__pycache__" in rel_parts:
            continue
        if any(part.startswith(".") for part in rel_parts):
            continue
        files.append(candidate)
    return files


def _module_name_for(root: Path, file_path: Path) -> str:
    rel = file_path.resolve().relative_to(root.resolve())
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _load_modules_jsonl(path: Path) -> set[str]:
    modules: set[str] = set()
    if not path.exists():
        return modules
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            module_name = row.get("module_name")
            if isinstance(module_name, str) and module_name:
                modules.add(module_name)
    return modules


def _collect_import_edges(analyses: Mapping[str, ModuleAnalysis]) -> list[tuple[str, str]]:
    return [
        (module, edge.dst_module)
        for module, analysis in analyses.items()
        for edge in analysis.imports
        if edge.dst_module
    ]


def _relative_out_of_bounds(module_name: str, edge: ImportEdge) -> bool:
    if edge.level <= 0:
        return False
    depth = len(module_name.split(".")) if module_name else 0
    return edge.level > depth


def _is_local_module(root: Path, module_name: str) -> bool:
    if not module_name:
        return False
    candidate = root.joinpath(*module_name.split("."))
    return bool(
        candidate.is_file()
        or candidate.with_suffix(".py").is_file()
        or (candidate.is_dir() and (candidate / "__init__.py").exists())
    )


def _missing_inits(root: Path) -> list[Path]:
    missing: list[Path] = []
    for directory in root.rglob("*"):
        if not directory.is_dir():
            continue
        rel_parts = directory.relative_to(root).parts
        if ".venv" in rel_parts or "__pycache__" in rel_parts:
            continue
        if any(part.startswith(".") for part in rel_parts):
            continue
        if not any(child.suffix == ".py" for child in directory.iterdir()):
            continue
        if not (directory / "__init__.py").exists():
            missing.append(directory)
    return missing


def _downstream_impact(edges: list[tuple[str, str]], start: str) -> list[str]:
    adjacency: dict[str, set[str]] = {}
    for src, dst in edges:
        adjacency.setdefault(src, set()).add(dst)
        adjacency.setdefault(dst, set())
    seen: set[str] = set()
    stack: list[str] = [start]
    downstream: list[str] = []
    while stack:
        node = stack.pop()
        for neighbor in adjacency.get(node, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            downstream.append(neighbor)
            stack.append(neighbor)
    downstream.sort()
    return downstream
