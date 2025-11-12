# SPDX-License-Identifier: MIT
"""Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

try:  # pragma: no cover - optional dependency
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    orjson = None  # type: ignore[assignment]


def _dump_json(obj: object) -> str:
    """Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.

    Parameters
    ----------
    obj : object
        Python object to serialize to JSON. Must be JSON-serializable (dicts,
        lists, strings, numbers, booleans, None). Complex objects are not
        supported.

    Returns
    -------
    str
        Pretty-printed JSON string with UTF-8 encoding.
    """
    if orjson is not None:
        try:
            return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8")
        except orjson.JSONEncodeError:  # type: ignore[attr-defined]
            pass
    return json.dumps(obj, indent=2, ensure_ascii=False)


def write_json(path: str | Path, obj: object) -> None:
    """Write an object as pretty-printed JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_json(obj), encoding="utf-8")


def write_jsonl(path: str | Path, rows: Iterable[dict[str, object]]) -> None:
    """Write newline-delimited JSON records."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_dump_json(row))
            handle.write("\n")


def _append_section(sections: list[str], title: str, lines: list[str]) -> None:
    if not lines:
        return
    sections.append(f"## {title}\n")
    sections.extend(lines)
    sections.append("")


def _format_imports(record: dict[str, object]) -> list[str]:
    formatted: list[str] = []
    imports_obj = record.get("imports")
    if not isinstance(imports_obj, list):
        return formatted
    for entry in imports_obj:
        if not isinstance(entry, Mapping):
            continue
        names = entry.get("names") or []
        if not isinstance(names, list):
            names = [str(names)]
        formatted.append(
            f"- from **{entry.get('module') or '(absolute)'}** import "
            f"{', '.join(names) or '(module import)'}"
            f"{' *' if entry.get('is_star') else ''}"
        )
    return formatted


def _format_definitions(record: dict[str, object]) -> list[str]:
    formatted: list[str] = []
    defs_obj = record.get("defs")
    if not isinstance(defs_obj, list):
        return formatted
    for definition in defs_obj:
        if not isinstance(definition, Mapping):
            continue
        kind = definition.get("kind")
        name = definition.get("name")
        lineno = definition.get("lineno")
        if isinstance(kind, str) and isinstance(name, str) and isinstance(lineno, int):
            formatted.append(f"- {kind}: `{name}` (line {lineno})")
    return formatted


def _format_graph_metrics(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for label in ("fan_in", "fan_out", "cycle_group"):
        value = record.get(label)
        if isinstance(value, int):
            lines.append(f"- **{label}**: {value}")
    return lines


def _format_exports(record: dict[str, object]) -> list[str]:
    exports = record.get("exports") or []
    if isinstance(exports, list) and exports:
        names = ", ".join(sorted(name for name in exports if isinstance(name, str)))
        return [names]
    return []


def _format_exports_resolved(record: dict[str, object]) -> list[str]:
    exports_resolved = record.get("exports_resolved") or {}
    lines: list[str] = []
    if isinstance(exports_resolved, Mapping):
        for origin, names in sorted(exports_resolved.items()):
            if isinstance(names, list):
                lines.append(f"- from **{origin}** import {', '.join(str(name) for name in names)}")
    return lines


def _format_reexports(record: dict[str, object]) -> list[str]:
    reexports = record.get("reexports") or {}
    lines: list[str] = []
    if isinstance(reexports, Mapping):
        for name, meta in sorted(reexports.items()):
            if not isinstance(meta, Mapping):
                continue
            origin = meta.get("from", "?")
            symbol = meta.get("symbol", "")
            suffix = f" ({symbol})" if symbol else ""
            lines.append(f"- `{name}` ← **{origin}**{suffix}")
    return lines


def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
    """Emit a human-friendly Markdown summary for a module record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = [f"# {record.get('path', 'Module')}\n"]
    docstring = record.get("docstring")
    if isinstance(docstring, str) and docstring.strip():
        sections.extend(["## Docstring\n", f"```\n{docstring.strip()}\n```\n"])
    _append_section(sections, "Imports", _format_imports(record))
    _append_section(sections, "Definitions", _format_definitions(record))
    _append_section(sections, "Dependency Graph", _format_graph_metrics(record))
    _append_section(sections, "Declared Exports (__all__)", _format_exports(record))
    _append_section(sections, "Resolved Star Imports", _format_exports_resolved(record))
    _append_section(sections, "Re-exports", _format_reexports(record))

    tags = record.get("tags") or []
    if isinstance(tags, list) and tags:
        sections.append("## Tags\n")
        sections.append(", ".join(sorted(tag for tag in tags if isinstance(tag, str))) + "\n")
    errors = record.get("errors") or []
    if isinstance(errors, list) and errors:
        sections.append("## Parse Errors / Notes\n")
        sections.extend(f"- {err}" for err in errors if isinstance(err, str))
    target.write_text("\n".join(sections), encoding="utf-8")
