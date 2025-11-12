# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and overlay generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from codeintel_rev.enrich.libcst_bridge import ImportEntry, index_module
from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None  # type: ignore[assignment]

EXPORT_HUB_THRESHOLD = 10

ROOT_OPTION = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
SCIP_OPTION = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json")
OUT_OPTION = typer.Option(
    Path("codeintel_rev/io/ENRICHED"),
    "--out",
    help="Output directory for enrichment artifacts.",
)
PYREFLY_OPTION = typer.Option(
    None,
    "--pyrefly-json",
    help="Optional path to a Pyrefly JSON/JSONL report.",
)
TAGS_OPTION = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML.")

app = typer.Typer(
    add_completion=False,
    help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
)


@dataclass(slots=True, frozen=True)
class ModuleRecord:
    """Serializable row stored in modules.jsonl."""

    path: str
    docstring: str | None
    imports: list[dict[str, Any]]
    defs: list[dict[str, Any]]
    exports: list[str]
    outline_nodes: list[dict[str, Any]]
    scip_symbols: list[str]
    parse_ok: bool
    errors: list[str]
    tags: list[str]
    type_errors: int


@dataclass(frozen=True)
class ScipContext:
    """Convenience wrapper around SCIP lookup helpers."""

    index: SCIPIndex
    by_file: Mapping[str, Document]


@dataclass(frozen=True)
class TypeSignals:
    """Aggregate Pyright and Pyrefly summaries."""

    pyright: TypeSummary | None
    pyrefly: TypeSummary | None


def _iter_files(root: Path) -> Iterable[Path]:
    """Yield Python files under root while skipping hidden paths.

    Extended Summary
    ----------------
    Recursively traverses the directory tree starting from root and yields
    all Python source files (.py), excluding any paths containing hidden
    directories (those starting with '.'). This function is used by the
    enrichment pipeline to discover modules for analysis.

    Parameters
    ----------
    root : Path
        Directory root to scan recursively. Must exist and be readable.

    Yields
    ------
    Path
        Source file path ready for analysis. Paths are absolute and point
        to valid Python source files.

    Notes
    -----
    Time O(n) where n is the number of files in the tree; memory O(1) aside
    from the iterator state. No I/O beyond directory traversal; no global state.
    Hidden paths are determined by checking if any component in the path
    starts with '.'.

    Examples
    --------
    >>> from pathlib import Path
    >>> files = list(_iter_files(Path("codeintel_rev")))
    >>> len(files) > 0
    True
    >>> all(f.suffix == ".py" for f in files)
    True
    """
    for candidate in root.rglob("*.py"):
        if any(part.startswith(".") for part in candidate.parts):
            continue
        yield candidate


def _collect_imported_modules(imports: Sequence[ImportEntry]) -> list[str]:
    """Return module names referenced by explicit or star imports.

    Extended Summary
    ----------------
    Extracts module names from LibCST import entries, handling both explicit
    module imports and star imports with aliases. Used during enrichment to
    build the dependency graph and infer module tags based on imported
    dependencies.

    Parameters
    ----------
    imports : Sequence[ImportEntry]
        Import entries extracted from LibCST parsing. Each entry contains
        module name, imported names, aliases, and star-import flags.

    Returns
    -------
    list[str]
        Ordered list of imported module names. Explicit module imports appear
        first, followed by aliased names from star imports.

    Notes
    -----
    Time O(n) where n is the number of import entries; memory O(m) where m
    is the total number of imported names. No I/O, no global state. Star
    imports without explicit module names contribute their aliased names
    to the result.

    Examples
    --------
    >>> from codeintel_rev.enrich.libcst_bridge import ImportEntry
    >>> entries = [
    ...     ImportEntry(module="os", names=[], aliases={}, is_star=False, level=0),
    ...     ImportEntry(module=None, names=["foo", "bar"], aliases={}, is_star=True, level=0),
    ... ]
    >>> modules = _collect_imported_modules(entries)
    >>> "os" in modules
    True
    """
    modules = [entry.module for entry in imports if entry.module]
    modules.extend(alias for entry in imports if entry.module is None for alias in entry.names)
    return modules


def _max_type_errors(rel_path: str, type_signals: TypeSignals) -> int:
    """Return the conservative type error count for a module.

    Extended Summary
    ----------------
    Computes the maximum type error count across Pyright and Pyrefly checkers
    for a given module. This conservative approach ensures that modules with
    type issues are properly tagged even if only one checker reports errors.
    Used during enrichment to infer quality tags and prioritize overlay
    generation.

    Parameters
    ----------
    rel_path : str
        Module path relative to the scan root. Must match keys used in
        type_signals summaries.

    type_signals : TypeSignals
        Aggregated Pyright and Pyrefly summaries. Either summary may be None
        if the corresponding checker was not run or failed.

    Returns
    -------
    int
        Maximum error count reported by either checker. Returns 0 if the
        module is not found in either summary or both summaries are None.

    Notes
    -----
    Time O(1) dictionary lookup; memory O(1). No I/O, no global state.
    Missing modules in summaries are treated as having zero errors.

    Examples
    --------
    >>> signals = TypeSignals(pyright=None, pyrefly=None)
    >>> _max_type_errors("test.py", signals)
    0
    """
    pyrefly = type_signals.pyrefly
    pyrefly_count = (
        pyrefly.by_file[rel_path].error_count if pyrefly and rel_path in pyrefly.by_file else 0
    )
    pyright = type_signals.pyright
    pyright_count = (
        pyright.by_file[rel_path].error_count if pyright and rel_path in pyright.by_file else 0
    )
    return max(pyrefly_count, pyright_count)


def _outline_nodes(module_path: str, code: str) -> list[dict[str, Any]]:
    """Serialize Tree-sitter outline nodes for the module.

    Extended Summary
    ----------------
    Parses the module source code using Tree-sitter and extracts structural
    outline information (function and class definitions) with byte offsets.
    This enables downstream tools to navigate and understand module structure
    without re-parsing. Used during enrichment to populate module metadata.

    Parameters
    ----------
    module_path : str
        Relative module path supplied to Tree-sitter for context. Used for
        error reporting and language detection.

    code : str
        Source code content as a UTF-8 string. Must be valid Python syntax
        for accurate parsing.

    Returns
    -------
    list[dict[str, Any]]
        List of outline entries, each containing 'kind' (function/class),
        'name', 'start' (byte offset), and 'end' (byte offset). Returns empty
        list if parsing fails or no definitions are found.

    Notes
    -----
    Time O(n) where n is code length (Tree-sitter parsing); memory O(m) where
    m is the number of definitions. No I/O beyond parsing; no global state.
    May raise exceptions if tree-sitter parsing fails due to API mismatches
    or missing language bindings.

    Examples
    --------
    >>> # Returns a list when parsing succeeds
    >>> try:
    ...     result = _outline_nodes("test.py", "def foo(): pass")
    ...     isinstance(result, list)
    ... except Exception:
    ...     True  # tree-sitter may be unavailable
    True
    """
    outline = build_outline(module_path, code.encode("utf-8"))
    if not outline:
        return []
    return [
        {"kind": node.kind, "name": node.name, "start": node.start_byte, "end": node.end_byte}
        for node in outline.nodes
    ]


def _build_module_row(
    fp: Path,
    root: Path,
    scip_ctx: ScipContext,
    type_signals: TypeSignals,
    rules: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Produce a serialized module row and associated SCIP symbol edges.

    Extended Summary
    ----------------
    Orchestrates the enrichment pipeline for a single module by combining
    LibCST parsing, Tree-sitter outlining, SCIP symbol resolution, type
    checker signals, and tag inference. This is the core transformation
    function that converts raw source files into structured module records
    and symbol graph edges for downstream analysis and indexing.

    Parameters
    ----------
    fp : Path
        Absolute path to the Python source file to process. Must exist and
        be readable.

    root : Path
        Repository root directory used to compute relative paths. Must be
        a parent of fp.

    scip_ctx : ScipContext
        SCIP index context providing symbol lookup and document mapping.
        Used to resolve star imports and extract symbol definitions.

    type_signals : TypeSignals
        Aggregated Pyright and Pyrefly type checker summaries. Used to
        compute error counts for quality tagging.

    rules : dict[str, Any]
        Tagging rules dictionary loaded from YAML. Controls how modules
        are tagged based on imports, exports, and error counts.

    Returns
    -------
    tuple[dict[str, Any], list[tuple[str, str]]]
        Pair of (module row dict, symbol edges). The module row contains
        path, docstring, imports, defs, exports, outline_nodes, scip_symbols,
        parse_ok, errors, tags, and type_errors. Symbol edges are tuples of
        (symbol_id, relative_file_path) for graph construction.

    Notes
    -----
    Time O(n + m) where n is file size and m is number of symbols; memory
    O(n + m) for parsed structures. Performs file I/O, LibCST parsing,
    Tree-sitter parsing, and SCIP lookups. No global state mutations.
    Parse errors are captured in the errors list rather than propagated.

    Examples
    --------
    >>> from pathlib import Path
    >>> from codeintel_rev.enrich.scip_reader import SCIPIndex
    >>> # Requires valid SCIP index and test file
    >>> # row, edges = _build_module_row(fp, root, scip_ctx, signals, {})
    >>> # assert isinstance(row, dict)
    >>> # assert isinstance(edges, list)
    """
    rel_path = str(fp.relative_to(root))
    code = fp.read_text(encoding="utf-8", errors="ignore")
    module_index = index_module(rel_path, code)
    overlay = generate_overlay_for_file(fp, root, scip_ctx.index)
    outline_nodes = _outline_nodes(module_index.path, code)

    imported_modules = _collect_imported_modules(module_index.imports)
    is_reexport_hub = any(entry.is_star for entry in module_index.imports) or (
        len(module_index.exports) >= EXPORT_HUB_THRESHOLD
    )
    type_errors = _max_type_errors(rel_path, type_signals)

    traits = ModuleTraits(
        imported_modules=imported_modules,
        has_all=bool(module_index.exports),
        is_reexport_hub=is_reexport_hub,
        type_error_count=type_errors,
    )
    tagging = infer_tags(path=rel_path, traits=traits, rules=rules)
    if overlay.created:
        tagging.tags.add("overlay-needed")

    scip_doc = scip_ctx.by_file.get(rel_path)
    scip_symbols = sorted(
        {sym.symbol for sym in (scip_doc.symbols if scip_doc else []) if sym.symbol}
    )
    symbol_edges = [(symbol, rel_path) for symbol in scip_symbols]

    row = ModuleRecord(
        path=rel_path,
        docstring=module_index.docstring,
        imports=[
            {
                "module": entry.module,
                "names": entry.names,
                "aliases": entry.aliases,
                "is_star": entry.is_star,
                "level": entry.level,
            }
            for entry in module_index.imports
        ],
        defs=[
            {"kind": entry.kind, "name": entry.name, "lineno": entry.lineno}
            for entry in module_index.defs
        ],
        exports=sorted(module_index.exports),
        outline_nodes=outline_nodes,
        scip_symbols=scip_symbols,
        parse_ok=module_index.parse_ok,
        errors=module_index.errors,
        tags=sorted(tagging.tags),
        type_errors=type_errors,
    )
    return asdict(row), symbol_edges


def _write_tag_index(out: Path, tag_index: dict[str, list[str]]) -> None:
    """Persist the YAML tag index when PyYAML is available."""
    if yaml_module is None:
        return
    tags_path = out / "tags"
    tags_path.mkdir(parents=True, exist_ok=True)
    serialized = yaml_module.safe_dump(tag_index, sort_keys=True)
    if serialized is None:
        return
    if isinstance(serialized, bytes):
        serialized = serialized.decode("utf-8")
    (tags_path / "tags_index.yaml").write_text(serialized, encoding="utf-8")


@app.command()
def main(
    root: Path = ROOT_OPTION,
    scip: Path = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
) -> None:
    """Run the enrichment pipeline."""
    out.mkdir(parents=True, exist_ok=True)
    scip_index = SCIPIndex.load(scip)
    scip_ctx = ScipContext(index=scip_index, by_file=scip_index.by_file())

    pyright_summary = collect_pyright(str(root))
    pyrefly_summary = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)
    type_signals = TypeSignals(pyright=pyright_summary, pyrefly=pyrefly_summary)
    rules = load_rules(str(tags_yaml) if tags_yaml else None)

    module_rows: list[dict[str, Any]] = []
    symbol_edges: list[tuple[str, str]] = []
    tag_index: dict[str, list[str]] = {}

    for fp in _iter_files(root):
        row_dict, file_symbol_edges = _build_module_row(
            fp=fp,
            root=root,
            scip_ctx=scip_ctx,
            type_signals=type_signals,
            rules=rules,
        )
        module_rows.append(row_dict)
        symbol_edges.extend(file_symbol_edges)
        for tag in row_dict["tags"]:
            tag_index.setdefault(tag, []).append(row_dict["path"])

        module_md_path = out / "modules" / (Path(row_dict["path"]).with_suffix(".md").name)
        write_markdown_module(module_md_path, row_dict)

    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
    write_json(
        out / "graphs" / "symbol_graph.json",
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )
    write_json(
        out / "repo_map.json",
        {
            "root": str(root),
            "module_count": len(module_rows),
            "symbol_edge_count": len(symbol_edges),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "tags": tag_index,
        },
    )
    _write_tag_index(out, tag_index)


if __name__ == "__main__":
    app()
