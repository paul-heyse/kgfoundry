"""Graph construction helpers for enrichment data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from codeintel_rev.enrich.graph.tarjan import tarjan_scc
from codeintel_rev.module_utils import module_name_candidates


@dataclass(frozen=True, slots=True)
class ImportGraph:
    """Immutable graph representation of module import relationships.

    Attributes
    ----------
    edges : dict[str, set[str]]
        Mapping from module names to sets of imported module names.
    fan_in : dict[str, int]
        Mapping from module names to their fan-in counts (number of modules
        that import this module).
    fan_out : dict[str, int]
        Mapping from module names to their fan-out counts (number of modules
        this module imports).
    cycle_group : dict[str, int]
        Mapping from module names to their strongly connected component group
        identifiers. Modules in the same cycle share the same group ID.
    """

    edges: dict[str, set[str]]
    fan_in: dict[str, int]
    fan_out: dict[str, int]
    cycle_group: dict[str, int]


def build_import_graph(
    rows: Sequence[Mapping[str, Any]],
    package_prefix: str | None = None,
) -> ImportGraph:
    """Build an import graph from module row data.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Sequence of module row dictionaries containing import metadata.
    package_prefix : str | None, optional
        Optional package prefix to filter modules. If provided, only modules
        within this package are included. Defaults to None.

    Returns
    -------
    ImportGraph
        Immutable graph representation with edges, fan-in/out counts, and
        cycle group assignments computed via Tarjan's algorithm.
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
        imports = _meta_imports(row)
        for dst_module in imports:
            dst_path = module_map.get(dst_module)
            if not dst_path or dst_path == src_path:
                continue
            edges[src_path].add(dst_path)

    fan_out = {src: len(dests) for src, dests in edges.items()}
    fan_in: dict[str, int] = {row["path"]: 0 for row in rows}
    for dests in edges.values():
        for dest in dests:
            fan_in[dest] = fan_in.get(dest, 0) + 1

    cycle_group = tarjan_scc(edges)
    return ImportGraph(edges=edges, fan_in=fan_in, fan_out=fan_out, cycle_group=cycle_group)


def _meta_imports(row: Mapping[str, Any]) -> set[str]:
    meta = row.get("meta")
    if not isinstance(meta, Mapping):
        return set()
    imports = meta.get("imports")
    if not isinstance(imports, list):
        return set()
    targets: set[str] = set()
    for entry in imports:
        if not isinstance(entry, Mapping):
            continue
        dst = entry.get("dst_module")
        if isinstance(dst, str) and dst:
            targets.add(dst)
    return targets
