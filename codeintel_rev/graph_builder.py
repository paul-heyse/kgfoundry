# SPDX-License-Identifier: MIT
"""Import graph builder utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from codeintel_rev.module_utils import (
    import_targets_for_entry,
    module_name_candidates,
    normalize_module_name,
)
from codeintel_rev.polars_support import resolve_polars_frame_factory
from codeintel_rev.typing import PolarsModule, gate_import


@dataclass(slots=True, frozen=True)
class ImportGraph:
    """Graph representation of intra-repo imports."""

    edges: dict[str, set[str]]
    fan_in: dict[str, int]
    fan_out: dict[str, int]
    cycle_group: dict[str, int]


def build_import_graph(
    rows: Sequence[Mapping[str, Any]],
    package_prefix: str | None = None,
) -> ImportGraph:
    """Build an import graph across repo modules.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Module metadata rows containing import information.
    package_prefix : str | None, optional
        Optional package prefix for module name normalization.

    Returns
    -------
    ImportGraph
        Data structure containing edges and per-module metrics.
    """
    module_map = {
        candidate: row["path"]
        for row in rows
        for candidate in module_name_candidates(row["path"], package_prefix)
        if candidate
    }
    edges: dict[str, set[str]] = {row["path"]: set() for row in rows}

    for row in rows:
        src_path = row["path"]
        current_module = normalize_module_name(src_path)
        for imp in row.get("imports") or []:
            if not isinstance(imp, dict):
                continue
            module = imp.get("module")
            names = imp.get("names") or []
            if not isinstance(names, list):
                names = []
            level = int(imp.get("level") or 0)
            targets = import_targets_for_entry(current_module, module, names, level)
            for target in targets:
                dst_path = module_map.get(target)
                if not dst_path:
                    continue
                if dst_path != src_path:
                    edges[src_path].add(dst_path)

    fan_out = {src: len(dests) for src, dests in edges.items()}
    fan_in: dict[str, int] = {row["path"]: 0 for row in rows}
    for dests in edges.values():
        for dest in dests:
            fan_in[dest] = fan_in.get(dest, 0) + 1

    cycle_group = _tarjan_scc(edges)
    return ImportGraph(edges=edges, fan_in=fan_in, fan_out=fan_out, cycle_group=cycle_group)


def write_import_graph(graph: ImportGraph, path: str | Path) -> None:
    """Write import edges to Parquet (or JSONL fallback)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"src_path": src, "dst_path": dst} for src, dests in graph.edges.items() for dst in dests
    ]
    if not records:
        target.write_text("", encoding="utf-8")
        return
    if _write_parquet(records, target):  # pragma: no cover - exercised in integration
        return
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(f"{record}\n")


def _tarjan_scc(edges: dict[str, set[str]]) -> dict[str, int]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    lowlink: dict[str, int] = {}
    order: dict[str, int] = {}
    component = 0
    assignment: dict[str, int] = {}

    def strongconnect(node: str) -> None:
        """Perform depth-first search to find strongly connected components.

        This nested function implements Tarjan's algorithm for finding strongly
        connected components (SCCs) in a directed graph. It performs a depth-first
        search, tracking discovery order and lowlink values to identify cycles.
        When a root node of an SCC is found (lowlink == order), all nodes on the
        stack up to that root are assigned to the same component.

        Parameters
        ----------
        node : str
            The current node being processed. Represents a module path in the import
            graph. The function recursively processes all neighbors (imported modules)
            to discover SCCs.

        Notes
        -----
        This function is part of Tarjan's SCC algorithm implementation. It uses
        closure variables (order, lowlink, stack, on_stack, assignment, component)
        to maintain algorithm state across recursive calls. Time complexity:
        O(V + E) where V is the number of nodes and E is the number of edges.
        The function modifies closure variables and is not thread-safe. It assigns
        component IDs to nodes that form cycles in the import graph, enabling
        cycle detection and grouping for dependency analysis.
        """
        nonlocal index, component
        order[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in edges.get(node, ()):
            if neighbor not in order:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], order[neighbor])
        if lowlink[node] == order[node]:
            while True:
                member = stack.pop()
                on_stack.remove(member)
                assignment[member] = component
                if member == node:
                    break
            component += 1

    for node in edges:
        if node not in order:
            strongconnect(node)
    return assignment


def _write_parquet(records: list[dict[str, str]], target: Path) -> bool:
    """Persist records to Parquet via polars when available.

    Parameters
    ----------
    records : list[dict[str, str]]
        List of dictionary records to write.
    target : Path
        File system path for the output Parquet file.

    Returns
    -------
    bool
        True if polars is available and write succeeded, False otherwise.
    """
    try:
        polars = cast("PolarsModule", gate_import("polars", "import graph export"))
    except ImportError:
        return False
    frame_factory = resolve_polars_frame_factory(polars)
    if frame_factory is None:
        return False
    data_frame = frame_factory(records)
    data_frame.write_parquet(str(target))
    return True
