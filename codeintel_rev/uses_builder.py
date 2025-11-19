# SPDX-License-Identifier: MIT
"""SCIP-based symbol use graph helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.enrich.graph.io import write_use_edges
from codeintel_rev.enrich.scip_reader import SCIPIndex


@dataclass(slots=True, frozen=True)
class UseGraph:
    """Definition-to-use relationships summarised by file.

    Attributes
    ----------
    uses_by_file : dict[str, set[str]]
        Dictionary mapping file paths to sets of symbol identifiers used in
        that file. Represents symbol usage grouped by file.
    symbol_usage : dict[str, int]
        Dictionary mapping symbol identifiers to their usage count across all
        files. Represents how many times each symbol is referenced.
    edges : list[tuple[str, str, str]]
        List of (def_path, use_path, symbol) tuples representing definition-to-use
        edges. def_path is where the symbol is defined, use_path is where it's
        used, and symbol is the symbol identifier.
    """

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


def write_use_graph(
    use_graph: UseGraph,
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Persist use graph edges to disk and return the output path.

    Parameters
    ----------
    use_graph : UseGraph
        Use graph containing edges to write.
    path : str | Path
        Target path for the output file (Parquet preferred).
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL path if Parquet is unavailable.
        Defaults to None.

    Returns
    -------
    Path
        The actual path used for writing (Parquet or JSONL fallback).
    """
    records = (
        {"def_path": def_path, "use_path": use_path, "symbol": symbol}
        for def_path, use_path, symbol in use_graph.edges
    )
    return write_use_edges(records, path, jsonl_fallback=jsonl_fallback)


def _is_definition(roles: list[str]) -> bool:
    """Check if any role indicates a definition.

    Parameters
    ----------
    roles : list[str]
        List of role strings to check.

    Returns
    -------
    bool
        True if any role contains "definition" or ends with "def", False otherwise.
    """
    for role in roles:
        normalized = role.lower()
        if "definition" in normalized or normalized.endswith("def"):
            return True
    return False
