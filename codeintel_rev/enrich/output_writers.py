# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _dump_json(obj: Any) -> str:
    try:
        import orjson  # type: ignore[import-not-found]

        return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8")
    except Exception:
        return json.dumps(obj, indent=2, ensure_ascii=False)


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump_json(obj), encoding="utf-8")


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(_dump_json(r))
            f.write("\n")


def write_markdown_module(path: str | Path, record: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"# {record.get('path', 'Module')}\n"]
    if record.get("docstring"):
        parts.append("## Docstring\n")
        parts.append("```\n" + record["docstring"].strip() + "\n```\n")
    if record.get("imports"):
        parts.append("## Imports\n")
        for imp in record["imports"]:
            mod = imp.get("module") or ""
            names = ", ".join(imp.get("names") or [])
            star = " *" if imp.get("is_star") else ""
            parts.append(
                f"- from **{mod or '(absolute)'}** import {names or '(module import)'}{star}"
            )
        parts.append("")
    if record.get("defs"):
        parts.append("## Definitions\n")
        for d in record["defs"]:
            parts.append(f"- {d['kind']}: `{d['name']}` (line {d['lineno']})")
        parts.append("")
    if record.get("tags"):
        parts.append("## Tags\n")
        parts.append(", ".join(sorted(record["tags"])) + "\n")
    if record.get("errors"):
        parts.append("## Parse Errors / Notes\n")
        for e in record["errors"]:
            parts.append(f"- {e}")
    p.write_text("\n".join(parts), encoding="utf-8")
