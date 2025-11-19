"""Helpers for serializing ModuleAnalysis payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeintel_rev.enrich.types import (
    DefinitionInfo,
    DocInfo,
    ExportItem,
    ImportEdge,
    LegacyImportRecord,
    ModuleAnalysis,
    ModuleMetrics,
)

__all__ = ["module_analysis_to_meta"]


def module_analysis_to_meta(analysis: ModuleAnalysis) -> dict[str, Any]:
    """Return a JSON-serializable mapping for ``analysis``.

    Parameters
    ----------
    analysis : ModuleAnalysis
        Module analysis result to serialize.

    Returns
    -------
    dict[str, Any]
        Normalized metadata payload containing imports, exports, docs, metrics,
        and definitions.
    """
    return {
        "module": analysis.module,
        "path": _as_posix(analysis.path),
        "imports": [_serialize_import(edge) for edge in analysis.imports],
        "exports": [_serialize_export(item) for item in analysis.exports],
        "docs": _serialize_docs(analysis.docs),
        "metrics": _serialize_metrics(analysis.metrics),
        "definitions": [_serialize_definition(item) for item in analysis.definitions],
        "legacy_imports": [_serialize_legacy_import(entry) for entry in analysis.legacy_imports],
    }


def _serialize_import(edge: ImportEdge) -> dict[str, Any]:
    return {
        "src_module": edge.src_module,
        "dst_module": edge.dst_module,
        "alias": edge.alias,
        "level": edge.level,
    }


def _serialize_export(item: ExportItem) -> dict[str, Any]:
    return {
        "module": item.module,
        "name": item.name,
        "kind": item.kind,
        "via_dunder_all": item.via_dunder_all,
    }


def _serialize_docs(info: DocInfo) -> dict[str, Any]:
    return {
        "module_docstring": info.module_docstring,
        "module_has_doc": info.module_has_doc,
        "classes_with_doc": info.classes_with_doc,
        "classes_total": info.classes_total,
        "functions_with_doc": info.functions_with_doc,
        "functions_total": info.functions_total,
    }


def _serialize_metrics(metrics: ModuleMetrics) -> dict[str, Any]:
    return {
        "module": metrics.module,
        "annotated_defs": metrics.annotated_defs,
        "defs_total": metrics.defs_total,
        "annotation_ratio": metrics.annotation_ratio,
        "has_top_level_side_effects": metrics.has_top_level_side_effects,
    }


def _serialize_definition(defn: DefinitionInfo) -> dict[str, Any]:
    return {
        "module": defn.module,
        "name": defn.name,
        "kind": defn.kind,
        "lineno": defn.lineno,
    }


def _serialize_legacy_import(entry: LegacyImportRecord) -> dict[str, Any]:
    return {
        "module": entry.module,
        "names": list(entry.names),
        "aliases": dict(entry.aliases),
        "is_star": entry.is_star,
        "level": entry.level,
    }


def _as_posix(path: Path) -> str:
    return path.as_posix()
