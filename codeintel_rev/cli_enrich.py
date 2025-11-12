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
from codeintel_rev.enrich.tagging import infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore[assignment]

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


@dataclass(slots=True)
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
    """Yield Python files under ``root`` while skipping hidden paths.

    Yields
    ------
    Path
        Source file ready for analysis.
    """
    for candidate in root.rglob("*.py"):
        if any(part.startswith(".") for part in candidate.parts):
            continue
        yield candidate


def _collect_imported_modules(imports: Sequence[ImportEntry]) -> list[str]:
    """Return module names referenced by explicit or star imports.

    Parameters
    ----------
    imports
        Import entries extracted from LibCST.

    Returns
    -------
    list[str]
        Ordered list of imported module names.
    """
    modules = [entry.module for entry in imports if entry.module]
    modules.extend(alias for entry in imports if entry.module is None for alias in entry.names)
    return modules


def _max_type_errors(rel_path: str, type_signals: TypeSignals) -> int:
    """Return the conservative type error count for a module.

    Parameters
    ----------
    rel_path
        Module path relative to the scan root.
    type_signals
        Aggregated Pyright and Pyrefly summaries.

    Returns
    -------
    int
        Maximum error count reported by either checker.
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

    Parameters
    ----------
    module_path
        Relative module path supplied to Tree-sitter.
    code
        Source code.

    Returns
    -------
    list[dict[str, Any]]
        Outline entries capturing start/end byte offsets.
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

    Returns
    -------
    tuple[dict[str, Any], list[tuple[str, str]]]
        Pair of module row dict and `(symbol, file)` edges.
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

    tagging = infer_tags(
        path=rel_path,
        imported_modules=imported_modules,
        has_all=bool(module_index.exports),
        is_reexport_hub=is_reexport_hub,
        type_error_count=type_errors,
        rules=rules,
    )
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
    if yaml is None:
        return
    tags_path = out / "tags"
    tags_path.mkdir(parents=True, exist_ok=True)
    (tags_path / "tags_index.yaml").write_text(
        yaml.safe_dump(tag_index, sort_keys=True),
        encoding="utf-8",  # type: ignore[union-attr]
    )


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
