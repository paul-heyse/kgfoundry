# SPDX-License-Identifier: MIT
"""Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

try:  # pragma: no cover - optional dependency
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    orjson = None  # type: ignore[assignment]


def _dump_json(obj: object) -> str:
    """Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.

    Returns
    -------
    str
        Pretty-printed JSON string.
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


def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
    """Emit a human-friendly Markdown summary for a module record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = [f"# {record.get('path', 'Module')}\n"]
    docstring = record.get("docstring")
    if isinstance(docstring, str) and docstring.strip():
        sections.extend(["## Docstring\n", f"```\n{docstring.strip()}\n```\n"])
    imports = record.get("imports") or []
    if isinstance(imports, list) and imports:
        sections.append("## Imports\n")
        sections.extend(
            f"- from **{imp.get('module') or '(absolute)'}** import "
            f"{', '.join(imp.get('names') or []) or '(module import)'}"
            f"{' *' if imp.get('is_star') else ''}"
            for imp in imports
            if isinstance(imp, dict)
        )
        sections.append("")
    defs = record.get("defs") or []
    if isinstance(defs, list) and defs:
        sections.append("## Definitions\n")
        sections.extend(
            f"- {definition['kind']}: `{definition['name']}` (line {definition['lineno']})"
            for definition in defs
            if isinstance(definition, dict)
        )
        sections.append("")
    tags = record.get("tags") or []
    if isinstance(tags, list) and tags:
        sections.append("## Tags\n")
        sections.append(", ".join(sorted(tag for tag in tags if isinstance(tag, str))) + "\n")
    errors = record.get("errors") or []
    if isinstance(errors, list) and errors:
        sections.append("## Parse Errors / Notes\n")
        sections.extend(f"- {err}" for err in errors if isinstance(err, str))
    target.write_text("\n".join(sections), encoding="utf-8")
