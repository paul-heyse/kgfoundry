"""Edge writers for enrichment graphs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl


def write_import_edges(
    graph: ImportGraph,
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
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

    Returns
    -------
    Path
        Path to the file that was actually written (Parquet or JSONL).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    records = [
        {"src_path": src, "dst_path": dst} for src, dests in graph.edges.items() for dst in dests
    ]
    used_path, _ = write_parquet_or_jsonl(target, fallback, records)
    return used_path


def write_use_edges(
    edges: Iterable[Mapping[str, str]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write use edges to Parquet or JSONL file.

    Parameters
    ----------
    edges : Iterable[Mapping[str, str]]
        Iterable of edge dictionaries to serialize.
    path : str | Path
        Target output file path (prefer Parquet, fallback to JSONL).
    jsonl_fallback : Path | None, optional
        Optional explicit fallback JSONL path. If None, uses path with .jsonl
        extension. Defaults to None.

    Returns
    -------
    Path
        Path to the file that was actually written (Parquet or JSONL).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    used_path, _ = write_parquet_or_jsonl(target, fallback, edges)
    return used_path
