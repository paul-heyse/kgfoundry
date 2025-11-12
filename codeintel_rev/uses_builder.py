# SPDX-License-Identifier: MIT
"""SCIP-based symbol use graph helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - optional dependency
    import polars as pl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]

from codeintel_rev.enrich.scip_reader import SCIPIndex


@dataclass(slots=True, frozen=True)
class UseGraph:
    """Definition-to-use relationships summarised by file."""

    uses_by_file: dict[str, set[str]]
    symbol_usage: dict[str, int]
    edges: list[tuple[str, str, str]]  # (def_path, use_path, symbol)


def build_use_graph(index: SCIPIndex) -> UseGraph:
    """Build a use graph from SCIP occurrences.

    Parameters
    ----------
    index : SCIPIndex
        SCIP index containing symbol definitions and occurrences.

    Returns
    -------
    UseGraph
        Definition-to-use relationships derived from the SCIP index.
    """
    symbol_defs: dict[str, str] = {}
    for doc in index.documents:
        for occurrence in doc.occurrences:
            if _is_definition(occurrence.roles):
                symbol_defs.setdefault(occurrence.symbol, doc.path)

    uses_by_file: dict[str, set[str]] = {}
    symbol_usage: dict[str, int] = {}
    edges: list[tuple[str, str, str]] = []

    for doc in index.documents:
        for occurrence in doc.occurrences:
            symbol = occurrence.symbol
            def_path = symbol_defs.get(symbol)
            if not def_path or def_path == doc.path:
                continue
            uses_by_file.setdefault(def_path, set()).add(doc.path)
            symbol_usage[def_path] = symbol_usage.get(def_path, 0) + 1
            edges.append((def_path, doc.path, symbol))

    return UseGraph(uses_by_file=uses_by_file, symbol_usage=symbol_usage, edges=edges)


def write_use_graph(use_graph: UseGraph, path: str | Path) -> None:
    """Persist use graph edges to Parquet (or JSONL fallback).

    Parameters
    ----------
    use_graph : UseGraph
        Graph to serialize.
    path : str | Path
        Destination file path.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"def_path": def_path, "use_path": use_path, "symbol": symbol}
        for def_path, use_path, symbol in use_graph.edges
    ]
    if not records:
        target.write_text("", encoding="utf-8")
        return
    if pl is not None:  # pragma: no cover
        pl.DataFrame(records).write_parquet(target)
    else:
        with target.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(f"{record}\n")


def _is_definition(roles: list[str]) -> bool:
    for role in roles:
        normalized = role.lower()
        if "definition" in normalized or normalized.endswith("def"):
            return True
    return False
