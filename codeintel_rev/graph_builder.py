# SPDX-License-Identifier: MIT
"""Backwards-compatible import graph helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.graph.builders import build_import_graph as _build_import_graph
from codeintel_rev.enrich.graph.io import write_import_edges

__all__ = ["ImportGraph", "build_import_graph", "write_import_graph"]


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
    return _build_import_graph(rows, package_prefix)


def write_import_graph(
    graph: ImportGraph,
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
    module_by_path: Mapping[str, str] | None = None,
) -> Path:
    """Write import graph edges to Parquet or JSONL file.

    Parameters
    ----------
    graph : ImportGraph
        Import graph containing edges to serialize.
    path : str | Path
        Target output file path (prefer Parquet, fallback to JSONL).
    jsonl_fallback : Path | None, optional
        Optional explicit fallback JSONL path. If None, uses path with .jsonl
        extension. Defaults to None.
    module_by_path : Mapping[str, str] | None, optional
        Optional mapping from repo-relative paths to module names. When
        provided, exported edges use module names instead of raw paths.

    Returns
    -------
    Path
        Path to the file that was actually written (Parquet or JSONL).
    """
    return write_import_edges(
        graph,
        path,
        jsonl_fallback=jsonl_fallback,
        module_by_path=module_by_path,
    )
