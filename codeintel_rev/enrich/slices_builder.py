# SPDX-License-Identifier: MIT
"""Utilities for generating opt-in LLM slice packs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.output_writers import write_json, write_markdown_module

__all__ = ["SliceRecord", "build_slice_record", "write_slice"]


@dataclass(slots=True, frozen=True)
class SliceRecord:
    """Serializable context packet describing a module and its surroundings."""

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
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _slice_id(path: str, module_name: str | None) -> str:
    from hashlib import sha1

    digest = sha1(path.encode("utf-8"))
    if module_name:
        digest.update(b"|")
        digest.update(module_name.encode("utf-8"))
    return digest.hexdigest()[:12]


def build_slice_record(module_row: Mapping[str, Any]) -> SliceRecord:
    """Build a :class:`SliceRecord` from a module row dictionary."""
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
    return SliceRecord(
        slice_id=slice_id,
        path=path,
        module_name=module_name,
        exports=list(module_row.get("exports_declared") or module_row.get("exports") or []),
        imports=list(module_row.get("imports") or []),
        defs=list(module_row.get("defs") or []),
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
