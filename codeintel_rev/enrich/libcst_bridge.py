# SPDX-License-Identifier: MIT
"""LibCST-powered module analysis plus compatibility shims."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import libcst as cst
from libcst import MaybeSentinel

from codeintel_rev.enrich.aggregators.metrics import (
    finalize_annotation_ratio,
    set_side_effects_flag,
)
from codeintel_rev.enrich.types import ModuleAnalysis
from codeintel_rev.enrich.visitors.docs import DocVisitor
from codeintel_rev.enrich.visitors.exports import ExportsVisitor
from codeintel_rev.enrich.visitors.imports import ImportsVisitor

__all__ = [
    "DefEntry",
    "ImportEntry",
    "ModuleIndex",
    "analyze_module",
    "analyze_module_from_code",
    "index_module",
]


def _default_doc_metrics(*, has_summary: bool) -> dict[str, Any]:
    return {
        "has_summary": has_summary,
        "param_parity": True,
        "examples_present": False,
    }


def _default_complexity() -> dict[str, int]:
    return {"branches": 0, "cyclomatic": 1, "loc": 0}


def _empty_doc_metrics() -> dict[str, Any]:
    return _default_doc_metrics(has_summary=False)


@dataclass(frozen=True, slots=True)
class ImportEntry:
    """Legacy import entry consumed by downstream enrichment components."""

    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int


@dataclass(frozen=True, slots=True)
class DefEntry:
    """Legacy definition entry (name/kind/line number)."""

    kind: str
    name: str
    lineno: int | None


@dataclass(slots=True)
class ModuleIndex:
    """Compatibility structure exposing the historical ModuleIndex layout."""

    path: str
    imports: list[ImportEntry] = field(default_factory=list)
    defs: list[DefEntry] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)
    docstring: str | None = None
    doc_summary: str | None = None
    doc_metrics: dict[str, Any] = field(default_factory=_empty_doc_metrics)
    doc_items: list[dict[str, Any]] = field(default_factory=list)
    annotation_ratio: dict[str, float] = field(
        default_factory=lambda: {"params": 1.0, "returns": 1.0}
    )
    untyped_defs: int = 0
    side_effects: dict[str, bool] = field(default_factory=dict)
    raises: list[str] = field(default_factory=list)
    complexity: dict[str, int] = field(default_factory=_default_complexity)
    parse_ok: bool = True
    errors: list[str] = field(default_factory=list)


def analyze_module(repo_root: Path, file_path: Path) -> ModuleAnalysis:
    """Return ModuleAnalysis for ``file_path`` relative to ``repo_root``.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    file_path : Path
        Absolute path to the Python file to analyze.

    Returns
    -------
    ModuleAnalysis
        Aggregated analysis results for the module.
    """
    rel = _relative_path(repo_root, file_path)
    code = file_path.read_text(encoding="utf-8", errors="ignore")
    return analyze_module_from_code(rel, code)


def analyze_module_from_code(rel_path: str, code: str) -> ModuleAnalysis:
    """Return ModuleAnalysis for a module identified by ``rel_path``.

    Parameters
    ----------
    rel_path : str
        Repository-relative path of the module.
    code : str
        Full source code of the Python module as a string.

    Returns
    -------
    ModuleAnalysis
        Aggregated analysis results for the module.
    """
    module = cst.parse_module(code)
    wrapper = cst.MetadataWrapper(module)
    module_name = _module_name_from_rel_path(rel_path)

    imports_visitor = ImportsVisitor(module_name)
    wrapper.visit(imports_visitor)

    exports_visitor = ExportsVisitor(module_name)
    wrapper.visit(exports_visitor)
    exports_visitor.finalize_items()

    docs_visitor = DocVisitor(module_name)
    module.visit(docs_visitor)

    annotated_defs, defs_total = _count_annotated_defs(exports_visitor.function_nodes)
    metrics = finalize_annotation_ratio(
        module_name,
        annotated_defs=annotated_defs,
        defs_total=defs_total,
    )
    metrics = set_side_effects_flag(
        metrics,
        has_side_effects=_has_top_level_side_effects(module),
    )

    return ModuleAnalysis(
        path=Path(rel_path),
        module=module_name,
        imports=imports_visitor.edges,
        exports=exports_visitor.items,
        dunder_all=tuple(exports_visitor.dunder_all),
        docs=docs_visitor.build_info(),
        metrics=metrics,
        definitions=exports_visitor.definitions,
        legacy_imports=imports_visitor.legacy_imports,
    )


def index_module(path: str, code: str) -> ModuleIndex:
    """Return a legacy ModuleIndex for compatibility consumers.

    Parameters
    ----------
    path : str
        Repository-relative module path.
    code : str
        Source code for the module.

    Returns
    -------
    ModuleIndex
        Serialized module metadata used by legacy consumers.
    """
    _, module_index = index_module_with_analysis(path, code)
    return module_index


def index_module_with_analysis(path: str, code: str) -> tuple[ModuleAnalysis, ModuleIndex]:
    """Return both the ModuleAnalysis object and the legacy ModuleIndex.

    Parameters
    ----------
    path : str
        Repository-relative module path.
    code : str
        Source code for the module.

    Returns
    -------
    tuple[ModuleAnalysis, ModuleIndex]
        New-style analysis payload plus the compatibility record.
    """
    analysis = analyze_module_from_code(path, code)
    module_index = _analysis_to_module_index(path, analysis)
    return analysis, module_index


def _analysis_to_module_index(rel_path: str, analysis: ModuleAnalysis) -> ModuleIndex:
    imports = [
        ImportEntry(
            module=record.module,
            names=list(record.names),
            aliases=dict(record.aliases),
            is_star=record.is_star,
            level=record.level,
        )
        for record in analysis.legacy_imports
    ]
    defs = [
        DefEntry(kind=definition.kind, name=definition.name, lineno=definition.lineno)
        for definition in analysis.definitions
    ]
    if analysis.dunder_all:
        exports = set(analysis.dunder_all)
    else:
        exported_via_all = [item.name for item in analysis.exports if item.via_dunder_all]
        if exported_via_all:
            exports = set(exported_via_all)
        else:
            exports = {item.name for item in analysis.exports if not item.name.startswith("_")}
    docstring = analysis.docs.module_docstring
    ratio = analysis.metrics.annotation_ratio
    annotation_ratio = {"params": ratio, "returns": ratio}
    untyped = analysis.metrics.defs_total - analysis.metrics.annotated_defs
    side_effects = {"top_level": analysis.metrics.has_top_level_side_effects}

    return ModuleIndex(
        path=rel_path,
        imports=imports,
        defs=defs,
        exports=exports,
        docstring=docstring,
        doc_metrics=_default_doc_metrics(has_summary=bool(docstring)),
        doc_items=[],
        annotation_ratio=annotation_ratio,
        untyped_defs=max(untyped, 0),
        side_effects=side_effects,
        raises=[],
        complexity=_default_complexity(),
        parse_ok=True,
        errors=[],
    )


def _module_name_from_rel_path(rel_path: str) -> str:
    path = Path(rel_path)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _relative_path(repo_root: Path, file_path: Path) -> str:
    try:
        return str(file_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(file_path)


def _count_annotated_defs(functions: list[cst.FunctionDef]) -> tuple[int, int]:
    annotated = 0
    total = 0
    for fn in functions:
        total += 1
        if _function_is_annotated(fn):
            annotated += 1
    return annotated, total


def _function_is_annotated(node: cst.FunctionDef) -> bool:
    params = _collect_params(node.params)
    annotated_params = 0
    total_params = 0
    for param in params:
        name = param.name.value
        if name in {"self", "cls"}:
            continue
        total_params += 1
        if param.annotation is not None:
            annotated_params += 1
    params_ok = total_params == annotated_params if total_params else True
    return params_ok and node.returns is not None


def _collect_params(params: cst.Parameters) -> list[cst.Param]:
    collected: list[cst.Param] = [
        *params.posonly_params,
        *params.params,
        *params.kwonly_params,
    ]
    star_arg = _extract_param(params.star_arg)
    if star_arg is not None:
        collected.append(star_arg)
    star_kwarg = _extract_param(params.star_kwarg)
    if star_kwarg is not None:
        collected.append(star_kwarg)
    return collected


def _extract_param(candidate: object) -> cst.Param | None:
    if candidate is None or candidate is MaybeSentinel.DEFAULT:
        return None
    if isinstance(candidate, cst.Param):
        return candidate
    param_attr = getattr(candidate, "param", None)
    if isinstance(param_attr, cst.Param):
        return param_attr
    return None


def _has_top_level_side_effects(module: cst.Module) -> bool:
    body = list(module.body)
    if body and isinstance(body[0], cst.SimpleStatementLine):
        first = body[0].body[0]
        if isinstance(first, cst.Expr) and isinstance(first.value, cst.SimpleString):
            body = body[1:]
    for statement in body:
        if isinstance(statement, cst.SimpleStatementLine):
            for expr in statement.body:
                if isinstance(expr, cst.Assign):
                    targets = {getattr(target.target, "value", "") for target in expr.targets}
                    if "__all__" in targets:
                        continue
                if isinstance(expr, (cst.AnnAssign, cst.Assign, cst.Expr)):
                    return True
        elif not isinstance(statement, (cst.FunctionDef, cst.ClassDef, cst.ImportFrom, cst.Import)):
            return True
    return False
