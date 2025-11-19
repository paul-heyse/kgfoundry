"""Shared helpers for enrichment pipeline stages and tagging."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeintel_rev.enrich.ast_indexer import stable_module_path
from codeintel_rev.enrich.errors import IndexingError
from codeintel_rev.enrich.libcst_bridge import ModuleIndex, index_module_with_analysis
from codeintel_rev.enrich.meta_compat import (
    export_names_from_meta,
    has_dunder_all,
    import_entries,
)
from codeintel_rev.enrich.meta_compat import (
    imported_modules as meta_imported_modules,
)
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.module_meta import module_analysis_to_meta
from codeintel_rev.enrich.pathnorm import module_name_from_path, stable_id_for_path
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.enrich.types import ModuleAnalysis
from codeintel_rev.export_resolver import EXPORT_HUB_THRESHOLD

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from codeintel_rev.cli.enrich_pipeline import ScanInputs

LOGGER = logging.getLogger(__name__)

__all__ = [
    "apply_tagging",
    "build_module_row",
    "normalized_rel_path",
    "outline_nodes_for",
    "type_error_count",
]


def normalized_rel_path(path: Path, root: Path) -> str:
    """Return the normalized relative path for ``path`` under ``root``.

    Extended Summary
    ----------------
    Computes a stable, POSIX-style relative path from a file path and repository
    root. Used throughout the enrichment pipeline to generate consistent module
    identifiers and cross-references.

    Parameters
    ----------
    path : Path
        Absolute file path to normalize.
    root : Path
        Repository root directory. The returned path will be relative to this root.

    Returns
    -------
    str
        POSIX-style path relative to ``root``, normalized for cross-platform
        consistency.
    """
    return stable_module_path(root, path)


def build_module_row(
    fp: Path,
    root: Path,
    inputs: ScanInputs,
) -> tuple[ModuleRecord, list[tuple[str, str]]]:
    """Construct a ModuleRecord and symbol edges for ``fp``.

    Extended Summary
    ----------------
    Extracts module metadata and symbol graph edges from a Python source file
    using SCIP indexing and AST analysis. This is a core enrichment pipeline
    function that transforms raw source files into structured module records
    with symbol relationships.

    Parameters
    ----------
    fp : Path
        Absolute path to the Python source file to process.
    root : Path
        Repository root directory for computing relative paths.
    inputs : ScanInputs
        Pipeline context containing SCIP index, type signals, coverage data,
        and other enrichment inputs.

    Returns
    -------
    tuple[ModuleRecord, list[tuple[str, str]]]
        Module metadata row and symbol edges extracted from SCIP context.
        The edges are (source_symbol_id, target_symbol_id) tuples representing
        symbol relationships.
    """
    rel = normalized_rel_path(fp, root)
    repo_path = normalized_rel_path(fp, inputs.repo_root)
    module_name = module_name_from_path(inputs.repo_root, fp, inputs.package_prefix)
    stable_id = stable_id_for_path(repo_path)
    scip_symbols, symbol_edges = _scip_symbols_and_edges(rel, inputs)
    type_errors = type_error_count(rel, inputs)
    record = ModuleRecord(
        path=rel,
        repo_path=repo_path,
        module_name=module_name,
        stable_id=stable_id,
        scip_symbols=scip_symbols,
        type_errors=type_errors,
        type_error_count=type_errors,
        doc_metrics={
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        },
        annotation_ratio={"params": 1.0, "returns": 1.0},
        side_effects={
            "filesystem": False,
            "network": False,
            "subprocess": False,
            "database": False,
        },
        complexity={"branches": 0, "cyclomatic": 1, "loc": 0},
        covered_lines_ratio=_coverage_value(rel, inputs, "covered_lines_ratio"),
        covered_defs_ratio=_coverage_value(rel, inputs, "covered_defs_ratio"),
    )

    code = _read_module_source(fp, rel, record, inputs.max_file_bytes)
    if code is None:
        return record, symbol_edges

    try:
        idx, analysis = _index_module_safe(rel, code)
    except IndexingError as exc:  # pragma: no cover - difficult to trigger deterministically
        LOGGER.exception("LibCST index failed for %s", rel, extra=exc.log_extra())
        record.add_error(exc)
        return record, symbol_edges

    outline_nodes = _collect_outline_nodes(rel, code, record)
    _apply_index_results(record, idx, outline_nodes, analysis)
    record.config_refs = []
    return record, symbol_edges


def outline_nodes_for(rel_path: str, code: str) -> list[dict[str, Any]]:
    """Build Tree-sitter outline nodes for ``rel_path``.

    Extended Summary
    ----------------
    Parses source code using Tree-sitter to extract structural outline information
    including function/class names and their byte offsets. Used for code navigation
    and outline generation in the enrichment pipeline.

    Parameters
    ----------
    rel_path : str
        Relative path to the source file (used for language detection and error
        reporting).
    code : str
        Source code content to parse.

    Returns
    -------
    list[dict[str, Any]]
        Outline node structures capturing names and byte offsets. Each dict
        contains node metadata including name, kind, and position information.

    Raises
    ------
    IndexingError
        Raised when Tree-sitter parsing fails or the language cannot be determined.
    """
    try:
        outline = build_outline(rel_path, code.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive logging
        reason = "tree-sitter"
        raise IndexingError(reason, path=rel_path, detail=str(exc)) from exc
    if outline is None:
        return []
    return [
        {
            "kind": node.kind,
            "name": node.name,
            "start": node.start_byte,
            "end": node.end_byte,
        }
        for node in outline.nodes
    ]


def type_error_count(rel_path: str, inputs: ScanInputs) -> int:
    """Return the type error count for ``rel_path``.

    Extended Summary
    ----------------
    Retrieves the aggregated type error count for a source file from the pipeline
    context. Used for quality metrics and tagging decisions in the enrichment
    pipeline.

    Parameters
    ----------
    rel_path : str
        Relative path to the source file (must match keys in inputs.type_signals).
    inputs : ScanInputs
        Pipeline context containing type error signals indexed by relative path.

    Returns
    -------
    int
        Maximum of Pyrefly and Pyright error counts for the path. Returns 0 if
        no type signals are available for the path.
    """
    signal = inputs.type_signals.get(rel_path)
    return signal.total if signal else 0


def apply_tagging(rows: list[ModuleRecord], rules: Mapping[str, Any]) -> None:
    """Apply tagging rules to module rows and update their tags in-place."""
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str):
            continue
        traits = _traits_from_row(row)
        result = infer_tags(path=path, traits=traits, rules=rules)
        tag_set = set(row.get("tags") or [])
        tag_set.update(result.tags)
        row["tags"] = sorted(tag_set)


def _scip_symbols_and_edges(
    rel_path: str,
    inputs: ScanInputs,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Extract SCIP symbols and symbol edges for a file path.

    Parameters
    ----------
    rel_path : str
        Relative path to the source file (must match keys in inputs.scip_ctx.by_file).
    inputs : ScanInputs
        Pipeline context containing SCIP index with symbol information indexed by file path.

    Returns
    -------
    tuple[list[str], list[tuple[str, str]]]
        Tuple containing:
        - Sorted list of unique symbol identifiers found in the file
        - List of (symbol_id, file_path) tuples representing symbol-to-file edges
    """
    document = inputs.scip_ctx.by_file.get(rel_path)
    symbols = sorted(
        {symbol.symbol for symbol in (document.symbols if document else []) if symbol.symbol}
    )
    return symbols, [(symbol, rel_path) for symbol in symbols]


def _index_module_safe(rel_path: str, code: str) -> tuple[ModuleIndex, ModuleAnalysis]:
    """Index a module using LibCST with error handling.

    Parameters
    ----------
    rel_path : str
        Relative path to the module within the repository.
    code : str
        Source code to parse.

    Returns
    -------
    tuple[ModuleIndex, ModuleAnalysis]
        Legacy ModuleIndex plus the richer ModuleAnalysis payload.

    Raises
    ------
    IndexingError
        Raised when LibCST fails to parse ``code``.
    """
    try:
        analysis, module_index = index_module_with_analysis(rel_path, code)
    except Exception as exc:  # pragma: no cover - defensive
        reason = "libcst"
        raise IndexingError(reason, path=rel_path, detail=str(exc)) from exc
    return module_index, analysis


def _read_module_source(
    fp: Path,
    rel_path: str,
    record: ModuleRecord,
    max_file_bytes: int,
) -> str | None:
    """Read source code from a file with size and error checks.

    Parameters
    ----------
    fp : Path
        Absolute path to the source file to read.
    rel_path : str
        Relative path to the file (used for error reporting).
    record : ModuleRecord
        Module record to update with errors if reading fails or file is too large.
    max_file_bytes : int
        Maximum file size in bytes. Files exceeding this limit will not be read
        and an error will be added to the record.

    Returns
    -------
    str | None
        Source code content as a string if successfully read, or None if:
        - File stat fails (OSError)
        - File size exceeds max_file_bytes
        - File read fails (OSError)
        In all error cases, an IndexingError is added to the record.
    """
    try:
        file_size = fp.stat().st_size
    except OSError as exc:
        error = IndexingError("stat", path=rel_path, detail=str(exc))
        LOGGER.warning("Failed to stat %s", rel_path, exc_info=True)
        record.add_error(error)
        return None
    if file_size > max_file_bytes:
        detail = f"{file_size}>{max_file_bytes}"
        error = IndexingError("file-too-large", path=rel_path, detail=detail)
        record.add_error(error)
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        error = IndexingError("read", path=rel_path, detail=str(exc))
        LOGGER.warning("Failed to read %s", rel_path, exc_info=True)
        record.add_error(error)
        return None


def _collect_outline_nodes(
    rel_path: str,
    code: str,
    record: ModuleRecord,
) -> list[dict[str, Any]]:
    """Collect Tree-sitter outline nodes with error handling.

    Parameters
    ----------
    rel_path : str
        Relative path to the source file (used for language detection and error reporting).
    code : str
        Source code content to parse for outline extraction.
    record : ModuleRecord
        Module record to update with errors if outline extraction fails.

    Returns
    -------
    list[dict[str, Any]]
        List of outline node dictionaries containing kind, name, start, and end
        byte offsets. Returns an empty list if parsing fails (error is logged
        and added to record).
    """
    try:
        return outline_nodes_for(rel_path, code)
    except IndexingError as exc:
        LOGGER.warning("Tree-sitter outline failed for %s", rel_path, extra=exc.log_extra())
        record.add_error(exc)
        return []


def _apply_index_results(
    record: ModuleRecord,
    idx: ModuleIndex,
    outline_nodes: list[dict[str, Any]],
    analysis: ModuleAnalysis | None = None,
) -> None:
    """Apply LibCST indexing results to a module record.

    Updates the module record with all metadata extracted from LibCST indexing,
    including docstrings, imports, definitions, exports, type annotations, side
    effects, complexity metrics, and parse status. Also merges Tree-sitter outline
    nodes and any parsing errors.

    Parameters
    ----------
    record : ModuleRecord
        Module record to update with indexing results. Modified in-place.
    idx : ModuleIndex
        LibCST indexing results containing module metadata, docstrings, imports,
        definitions, exports, and analysis metrics.
    outline_nodes : list[dict[str, Any]]
        Tree-sitter outline nodes to attach to the record.
    analysis : ModuleAnalysis | None, optional
        Raw ModuleAnalysis payload used to populate `record["meta"]`.

    Notes
    -----
    This function mutates the record in-place, updating all fields related to
    documentation, imports, definitions, exports, type annotations, side effects,
    complexity, and parse status. Errors from indexing are appended to the record's
    errors list.
    """
    doc_metrics = dict(idx.doc_metrics)
    record.doc_metrics = doc_metrics
    has_summary = doc_metrics.get("has_summary")
    record.docstring = idx.docstring
    record.doc_summary = idx.doc_summary
    record.doc_has_summary = bool(has_summary)
    param_parity = doc_metrics.get("param_parity")
    record.doc_param_parity = bool(param_parity) if param_parity is not None else True
    record.doc_examples_present = bool(doc_metrics.get("examples_present"))
    record.imports = [
        {
            "module": entry.module,
            "names": list(entry.names),
            "aliases": dict(entry.aliases),
            "is_star": entry.is_star,
            "level": entry.level,
        }
        for entry in idx.imports
    ]
    record.defs = [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in idx.defs]
    record.exports = sorted(idx.exports)
    record.exports_declared = sorted(idx.exports)
    record.outline_nodes = outline_nodes
    record.parse_ok = idx.parse_ok
    if idx.errors:
        record.errors.extend(idx.errors)
    record.doc_items = idx.doc_items
    record.annotation_ratio = dict(idx.annotation_ratio)
    record.untyped_defs = idx.untyped_defs
    record.side_effects = dict(idx.side_effects)
    record.raises = list(idx.raises)
    record.complexity = dict(idx.complexity)
    if analysis is not None:
        record["meta"] = module_analysis_to_meta(analysis)


def _coverage_value(rel_path: str, inputs: ScanInputs, key: str) -> float:
    """Extract a coverage metric value for a file path.

    Parameters
    ----------
    rel_path : str
        Relative path to the source file (must match keys in inputs.coverage_map).
    inputs : ScanInputs
        Pipeline context containing coverage data indexed by relative path.
    key : str
        Coverage metric key to retrieve (e.g., "covered_lines_ratio", "covered_defs_ratio").

    Returns
    -------
    float
        Coverage metric value for the specified key, or 0.0 if the path is not
        in the coverage map or the key is not present in the entry.
    """
    entry = inputs.coverage_map.get(rel_path, {})
    return float(entry.get(key, 0.0))


def _traits_from_row(row: Mapping[str, Any]) -> ModuleTraits:
    """Extract module traits from a module record dictionary.

    Parses a module record dictionary to extract traits used for tagging decisions,
    including imports, exports, coverage, type errors, fan-in/fan-out metrics,
    hotspot scores, and documentation quality flags.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module record dictionary containing fields like imports, exports, coverage,
        type errors, fan metrics, and documentation flags.

    Returns
    -------
    ModuleTraits
        Extracted traits object containing:
        - imported_modules: List of imported module names
        - has_all: Whether __all__ is defined and non-empty
        - is_reexport_hub: Whether the module is a re-export hub (has star imports
          or many exports)
        - type_error_count: Number of type errors
        - fan_in, fan_out: Dependency metrics
        - hotspot_score: Code churn/activity score
        - covered_lines_ratio: Test coverage ratio (defaults to 1.0 if missing)
        - doc_has_summary, doc_param_parity: Documentation quality flags

    Notes
    -----
    This function performs defensive parsing with type coercion and defaults.
    Missing or invalid values are handled gracefully (e.g., coverage defaults to
    1.0, fan metrics default to 0, doc flags default to True if None).
    """
    imported_modules = meta_imported_modules(row)
    imports_field = import_entries(row)
    exports = export_names_from_meta(row)
    has_all = has_dunder_all(row)
    has_star = any(entry.is_star for entry in imports_field)
    is_reexport_hub = has_star or len(exports) >= EXPORT_HUB_THRESHOLD

    coverage_value = row.get("covered_lines_ratio")
    coverage_ratio = float(coverage_value) if isinstance(coverage_value, (int, float)) else 1.0

    fan_in_value = row.get("fan_in")
    fan_out_value = row.get("fan_out")
    hotspot_value = row.get("hotspot_score")

    type_error_value = row.get("type_error_count")
    if not isinstance(type_error_value, int):
        type_error_value = int(row.get("type_errors") or 0)

    doc_summary_flag = row.get("doc_has_summary")
    doc_parity_flag = row.get("doc_param_parity")

    return ModuleTraits(
        imported_modules=imported_modules,
        has_all=has_all,
        is_reexport_hub=is_reexport_hub,
        type_error_count=type_error_value,
        fan_in=int(fan_in_value) if isinstance(fan_in_value, int) else 0,
        fan_out=int(fan_out_value) if isinstance(fan_out_value, int) else 0,
        hotspot_score=float(hotspot_value) if isinstance(hotspot_value, (int, float)) else 0.0,
        covered_lines_ratio=coverage_ratio,
        doc_has_summary=bool(doc_summary_flag if doc_summary_flag is not None else True),
        doc_param_parity=bool(doc_parity_flag if doc_parity_flag is not None else True),
    )
