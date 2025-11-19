# SPDX-License-Identifier: MIT
"""Utilities for generating opt-in LLM slice packs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import blake2s
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.meta_compat import (
    definition_entries,
    export_names_from_meta,
    import_entries,
)
from codeintel_rev.enrich.output_writers import write_json, write_markdown_module

__all__ = ["SliceRecord", "build_slice_record", "write_slice"]


@dataclass(slots=True, frozen=True)
class SliceRecord:
    """Serializable context packet describing a module and its surroundings.

    Attributes
    ----------
    slice_id : str
        Unique identifier for this slice (e.g., "slice:path/to/module.py").
    path : str
        File path relative to repository root.
    module_name : str | None, optional
        Python module name. None if module name cannot be determined.
        Defaults to None.
    exports : list[str], optional
        List of symbol names exported by this module. Defaults to empty list.
    imports : list[dict[str, Any]], optional
        List of import statement dictionaries. Defaults to empty list.
    defs : list[dict[str, Any]], optional
        List of definition dictionaries. Defaults to empty list.
    doc_summary : str | None, optional
        Extracted docstring summary. None if no summary. Defaults to None.
    tags : list[str], optional
        List of tags inferred for this module. Defaults to empty list.
    graph : dict[str, Any], optional
        Dictionary of graph metrics (imports, uses, etc.). Defaults to empty
        dictionary.
    usage : dict[str, Any], optional
        Dictionary of usage metrics (fan-in, fan-out, etc.). Defaults to empty
        dictionary.
    coverage : dict[str, float], optional
        Dictionary of coverage metrics (lines, definitions, etc.).
        Defaults to empty dictionary.
    config_refs : list[str], optional
        List of configuration references. Defaults to empty list.
    owners : dict[str, Any], optional
        Dictionary of ownership metadata (owner, authors, bus factor).
        Defaults to empty dictionary.
    extras : dict[str, Any], optional
        Additional metadata fields. Defaults to empty dictionary.
    timestamp : str, optional
        ISO 8601 timestamp when this slice was created. Defaults to current
        UTC time.
    """

    slice_id: str
    path: str
    module_name: str | None = None
    exports: list[str] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    defs: list[dict[str, Any]] = field(default_factory=list)
    doc_summary: str | None = None
    tags: list[str] = field(default_factory=list)
    graph: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, float] = field(default_factory=dict)
    config_refs: list[str] = field(default_factory=list)
    owners: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=datetime.now(UTC).isoformat)


def _slice_id(path: str, module_name: str | None) -> str:
    """Generate a stable slice identifier from path and module name.

    Parameters
    ----------
    path : str
        File path used as the primary identifier component.
    module_name : str | None
        Optional module name to include in the hash. If provided, the identifier
        incorporates both path and module name for uniqueness.

    Returns
    -------
    str
        Hexadecimal hash string (first 12 characters of BLAKE2s digest) used
        as a stable slice identifier. The same path and module_name combination
        always produces the same slice_id.
    """
    digest = blake2s(path.encode("utf-8"))
    if module_name:
        digest.update(b"|")
        digest.update(module_name.encode("utf-8"))
    return digest.hexdigest()[:12]


def build_slice_record(module_row: Mapping[str, Any]) -> SliceRecord:
    """Build a :class:`SliceRecord` from a module row dictionary.

    This function constructs a SliceRecord from a module row dictionary containing
    path, module name, coverage metrics, and ownership information. The function
    extracts and validates fields from the dictionary, computes a slice ID, and
    builds a structured record suitable for serialization.

    Parameters
    ----------
    module_row : Mapping[str, Any]
        Dictionary containing module metadata with keys such as "path", "module_name",
        "covered_lines_ratio", "covered_defs_ratio", "owner", "primary_authors", etc.
        The dictionary is expected to contain module information from enrichment
        artifacts or database queries.

    Returns
    -------
    SliceRecord
        Structured slice description derived from module_row. The record includes
        path, module name, slice ID, coverage metrics (lines and definitions ratios),
        and ownership information (owner, primary authors). Missing or invalid
        values are handled gracefully with defaults (empty strings, zero ratios,
        empty lists).
    """
    path = str(module_row.get("path"))
    module_name = (
        module_row.get("module_name") if isinstance(module_row.get("module_name"), str) else None
    )
    slice_id = _slice_id(path, module_name)
    coverage = {
        "covered_lines_ratio": float(module_row.get("covered_lines_ratio") or 0.0),
        "covered_defs_ratio": float(module_row.get("covered_defs_ratio") or 0.0),
    }
    owners = {
        "owner": module_row.get("owner"),
        "primary_authors": list(module_row.get("primary_authors") or []),
        "bus_factor": float(module_row.get("bus_factor") or 0.0),
    }
    extras = {
        "doc_metrics": module_row.get("doc_metrics"),
        "hotspot_score": module_row.get("hotspot_score"),
        "stable_id": module_row.get("stable_id"),
        "exports_resolved": module_row.get("exports_resolved"),
    }
    exports = export_names_from_meta(module_row)
    imports = import_entries(module_row)
    defs = definition_entries(module_row)
    return SliceRecord(
        slice_id=slice_id,
        path=path,
        module_name=module_name,
        exports=exports,
        imports=imports,
        defs=defs,
        doc_summary=module_row.get("doc_summary"),
        tags=list(module_row.get("tags") or []),
        graph={
            "fan_in": int(module_row.get("fan_in") or 0),
            "fan_out": int(module_row.get("fan_out") or 0),
            "cycle_group": int(module_row.get("cycle_group") or -1),
        },
        usage={
            "used_by_files": int(module_row.get("used_by_files") or 0),
            "used_by_symbols": int(module_row.get("used_by_symbols") or 0),
        },
        coverage=coverage,
        config_refs=list(module_row.get("config_refs") or []),
        owners=owners,
        extras=extras,
    )


def write_slice(out_root: Path, record: SliceRecord) -> None:
    """Persist a slice pack (JSON + Markdown) under ``out_root/slices``."""
    base = out_root / "slices" / record.slice_id
    base.mkdir(parents=True, exist_ok=True)
    write_json(base / "slice.json", asdict(record))
    write_markdown_module(
        base / "context.md",
        {
            "path": record.path,
            "docstring": record.doc_summary or "",
            "imports": record.imports,
            "defs": record.defs,
            "tags": record.tags,
            "fan_in": record.graph.get("fan_in"),
            "fan_out": record.graph.get("fan_out"),
            "cycle_group": record.graph.get("cycle_group"),
            "owner": record.owners.get("owner"),
            "primary_authors": record.owners.get("primary_authors"),
            "bus_factor": record.owners.get("bus_factor"),
            "used_by_files": record.usage.get("used_by_files"),
            "used_by_symbols": record.usage.get("used_by_symbols"),
            "covered_lines_ratio": record.coverage.get("covered_lines_ratio"),
            "covered_defs_ratio": record.coverage.get("covered_defs_ratio"),
            "config_refs": record.config_refs,
            "errors": [],
        },
    )
