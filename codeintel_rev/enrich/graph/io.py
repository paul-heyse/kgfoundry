"""Edge writers for enrichment graphs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path

from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl
from codeintel_rev.ids.goid import GOID, CrosswalkRow


def _as_decimal(value: object) -> object:
    if isinstance(value, int):
        return Decimal(value)
    return value


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


def write_call_nodes(
    nodes: Iterable[Mapping[str, object]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write call graph nodes to disk.

    Parameters
    ----------
    nodes : Iterable[Mapping[str, object]]
        Iterable of call node dictionaries to write.
    path : str | Path
        Target file path. Written as Parquet if available, otherwise falls
        back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized = []
    for node in nodes:
        record = dict(node)
        record["goid_h128"] = _as_decimal(record.get("goid_h128"))
        normalized.append(record)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized)
    return used_path


def write_call_edges(
    edges: Iterable[Mapping[str, object]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write call graph edges to disk.

    Parameters
    ----------
    edges : Iterable[Mapping[str, object]]
        Iterable of call edge dictionaries to write.
    path : str | Path
        Target file path. Written as Parquet if available, otherwise falls
        back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized = []
    for edge in edges:
        record = dict(edge)
        record["caller_goid_h128"] = _as_decimal(record.get("caller_goid_h128"))
        record["callee_goid_h128"] = _as_decimal(record.get("callee_goid_h128"))
        normalized.append(record)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized)
    return used_path


def write_cfg_blocks(
    blocks: Iterable[Mapping[str, object]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write CFG block rows to disk.

    Parameters
    ----------
    blocks : Iterable[Mapping[str, object]]
        Iterable of CFG block dictionaries to write.
    path : str | Path
        Target file path. Written as Parquet if available, otherwise falls
        back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized = []
    for block in blocks:
        record = dict(block)
        record["function_goid_h128"] = _as_decimal(record.get("function_goid_h128"))
        normalized.append(record)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized)
    return used_path


def write_cfg_edges(
    edges: Iterable[Mapping[str, object]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write CFG edge rows to disk.

    Parameters
    ----------
    edges : Iterable[Mapping[str, object]]
        Iterable of CFG edge dictionaries to write.
    path : str | Path
        Target file path. Written as Parquet if available, otherwise falls
        back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized = []
    for edge in edges:
        record = dict(edge)
        record["function_goid_h128"] = _as_decimal(record.get("function_goid_h128"))
        normalized.append(record)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized)
    return used_path


def write_dfg_edges(
    edges: Iterable[Mapping[str, object]],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write DFG edge rows to disk.

    Parameters
    ----------
    edges : Iterable[Mapping[str, object]]
        Iterable of DFG edge dictionaries to write.
    path : str | Path
        Target file path. Written as Parquet if available, otherwise falls
        back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized = []
    for edge in edges:
        record = dict(edge)
        record["function_goid_h128"] = _as_decimal(record.get("function_goid_h128"))
        normalized.append(record)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized)
    return used_path


def write_goid_registry(
    goids: Iterable[GOID],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write GOID registry entries to disk.

    Parameters
    ----------
    goids : Iterable[GOID]
        Iterable of GOID objects to write to the registry file.
    path : str | Path
        Target file path for the registry. Written as Parquet if available,
        otherwise falls back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).

    Notes
    -----
    This function writes GOID registry entries in Parquet format when available,
    falling back to JSONL format if Parquet writing fails. Each GOID is
    converted to a dictionary row with all GOID attributes.
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    rows = [
        {
            "goid_h128": Decimal(goid.h128),
            "urn": goid.urn,
            "repo": goid.repo,
            "commit": goid.commit,
            "rel_path": goid.rel_path,
            "language": goid.language,
            "kind": goid.kind,
            "qualname": goid.qualname,
            "start_line": goid.start_line,
            "end_line": goid.end_line,
        }
        for goid in goids
    ]
    used_path, _ = write_parquet_or_jsonl(target, fallback, rows)
    return used_path


def write_goid_crosswalk(
    crosswalk_rows: Iterable[CrosswalkRow],
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Write GOID crosswalk rows to disk.

    Parameters
    ----------
    crosswalk_rows : Iterable[CrosswalkRow]
        Iterable of crosswalk row dictionaries mapping GOIDs to AST nodes
        and chunk identifiers.
    path : str | Path
        Target file path for the crosswalk. Written as Parquet if available,
        otherwise falls back to JSONL.
    jsonl_fallback : Path | None, optional
        Optional fallback JSONL file path. If None, uses the target path with
        .jsonl extension.

    Returns
    -------
    Path
        Path to the actual file written (Parquet or JSONL fallback).

    Notes
    -----
    This function writes crosswalk rows in Parquet format when available,
    falling back to JSONL format if Parquet writing fails. Crosswalk rows
    link GOID hashes to AST node types and chunk identifiers.
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    normalized_rows: list[dict[str, object]] = []
    for row in crosswalk_rows:
        normalized_row = dict(row)
        normalized_row["goid_h128"] = _as_decimal(normalized_row.get("goid_h128"))
        normalized_rows.append(normalized_row)
    used_path, _ = write_parquet_or_jsonl(target, fallback, normalized_rows)
    return used_path
