# SPDX-License-Identifier: MIT
"""Config awareness helpers (YAML/TOML/JSON/Markdown)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CONFIG_EXTENSIONS = (".yaml", ".yml", ".toml", ".json", ".md")


def index_config_files(
    root: Path,
    patterns: tuple[str, ...] = CONFIG_EXTENSIONS,
) -> list[dict[str, Any]]:
    """Return config metadata (path + extracted keys/headings).

    Parameters
    ----------
    root : Path
        Root directory to search for configuration files.
    patterns : tuple[str, ...], optional
        File extension patterns to match (defaults to CONFIG_EXTENSIONS).

    Returns
    -------
    list[dict[str, Any]]
        Records containing ``path``, ``keys``, and ``references``.
    """
    records: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in root.rglob(f"*{pattern}"):
            if not path.is_file():
                continue
            records.append(
                {
                    "path": str(path.relative_to(root)),
                    "keys": _extract_keys(path),
                    "references": [],
                }
            )
    return records


def _extract_keys(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return _extract_yaml_keys(path)
    if suffix == ".toml":
        return _extract_toml_keys(path)
    if suffix == ".json":
        return _extract_json_keys(path)
    if suffix == ".md":
        return _extract_markdown_headings(path)
    return []


def _extract_yaml_keys(path: Path) -> list[str]:
    keys: list[str] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+):")
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            keys.append(match.group(1))
    return keys


def _extract_toml_keys(path: Path) -> list[str]:
    keys: list[str] = []
    pattern = re.compile(r"^\[([A-Za-z0-9_.-]+)\]")
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            keys.append(match.group(1))
    return keys


def _extract_json_keys(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    def flatten(obj: object, prefix: str = "") -> list[str]:
        if isinstance(obj, dict):
            result: list[str] = []
            for key, value in obj.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                result.append(new_prefix)
                result.extend(flatten(value, new_prefix))
            return result
        if isinstance(obj, list):
            result = []
            for idx, item in enumerate(obj):
                new_prefix = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                result.append(new_prefix)
                result.extend(flatten(item, new_prefix))
            return result
        return []

    return flatten(payload)


def _extract_markdown_headings(path: Path) -> list[str]:
    return [
        raw_line.lstrip("#").strip()
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if raw_line.startswith("#")
    ]
