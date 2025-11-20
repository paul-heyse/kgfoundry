"""Edge writers for enrichment graphs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl
from codeintel_rev.ids.goid import GOID, CrosswalkRow

try:  # pragma: no cover - optional dependency
    import pyarrow as pa
except ImportError:  # pragma: no cover - optional dependency
    pa = None

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pyarrow import Schema

    from codeintel_rev.uses_builder import UseGraph
else:  # pragma: no cover - runtime fallback
    Schema = Any
    UseGraph = Any

IMPORT_EDGES_SCHEMA: Schema | None = (
    pa.schema(
        [
            pa.field("src_module", pa.string()),
            pa.field("dst_module", pa.string()),
            pa.field("src_fan_out", pa.int32()),
            pa.field("dst_fan_in", pa.int32()),
            pa.field("cycle_group", pa.int32()),
        ]
    )
    if pa is not None
    else None
)

USE_EDGES_SCHEMA: Schema | None = (
    pa.schema(
        [
            pa.field("symbol", pa.string()),
            pa.field("def_path", pa.string()),
            pa.field("use_path", pa.string()),
            pa.field("same_file", pa.bool_()),
            pa.field("same_module", pa.bool_()),
        ]
    )
    if pa is not None
    else None
)


def _as_decimal(value: object) -> object:
    if isinstance(value, int):
        return Decimal(value)
    return value


def write_import_edges(
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
        provided, edge endpoints are rendered using module names; otherwise
        raw paths are used.

    Returns
    -------
    Path
        Path to the file that was actually written (Parquet or JSONL).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")

    def _module_for(path_key: str) -> str:
        if module_by_path is None:
            return path_key
        mapped = module_by_path.get(path_key)
        return mapped or path_key

    def _rows() -> Iterator[Mapping[str, object]]:
        for src, dests in graph.edges.items():
            src_fan_out = graph.fan_out.get(src, 0)
            cycle_group = graph.cycle_group.get(src, -1)
            for dst in dests:
                yield {
                    "src_module": _module_for(src),
                    "dst_module": _module_for(dst),
                    "src_fan_out": src_fan_out,
                    "dst_fan_in": graph.fan_in.get(dst, 0),
                    "cycle_group": cycle_group,
                }

    used_path, _ = write_parquet_or_jsonl(
        target,
        fallback,
        _rows(),
        schema=IMPORT_EDGES_SCHEMA,
    )
    return used_path


def write_use_edges(
    graph: UseGraph,
    path: str | Path,
    *,
    jsonl_fallback: Path | None = None,
    module_by_path: Mapping[str, str] | None = None,
) -> Path:
    """Write def-use edges to Parquet or JSONL file.

    Parameters
    ----------
    graph : UseGraph
        Use graph instance containing definition-to-use edges.
    path : str | Path
        Target output file path (prefer Parquet, fallback to JSONL).
    jsonl_fallback : Path | None, optional
        Optional explicit fallback JSONL path. If None, uses path with .jsonl
        extension. Defaults to None.
    module_by_path : Mapping[str, str] | None, optional
        Optional mapping from repo-relative paths to module names to compute the
        ``same_module`` flag. Defaults to None.

    Returns
    -------
    Path
        Path to the file that was actually written (Parquet or JSONL).
    """
    target = Path(path)
    fallback = jsonl_fallback or target.with_suffix(".jsonl")
    module_lookup = module_by_path or {}

    def _rows() -> Iterator[Mapping[str, object]]:
        for def_path, use_path, symbol in graph.edges:
            def_module = module_lookup.get(def_path)
            use_module = module_lookup.get(use_path)
            yield {
                "symbol": symbol,
                "def_path": def_path,
                "use_path": use_path,
                "same_file": def_path == use_path,
                "same_module": bool(def_module and def_module == use_module),
            }

    used_path, _ = write_parquet_or_jsonl(
        target,
        fallback,
        _rows(),
        schema=USE_EDGES_SCHEMA,
    )
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
