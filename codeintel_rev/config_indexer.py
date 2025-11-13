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
        """Recursively flatten nested JSON structure into dot-notation key paths.

        This nested function traverses JSON objects and arrays recursively, building
        dot-notation paths for all keys. Dictionary keys are joined with dots (e.g.,
        "config.database.host"), while array indices are represented with brackets
        (e.g., "items[0].name"). The function handles nested structures of arbitrary
        depth and returns all key paths found in the structure.

        Parameters
        ----------
        obj : object
            JSON value to flatten (dict, list, or primitive). Dictionaries and lists
            are traversed recursively; primitives are ignored (no keys to extract).
        prefix : str, optional
            Current path prefix for building nested key paths. Empty string for root
            level keys. Used recursively to build dot-notation paths.

        Returns
        -------
        list[str]
            List of dot-notation key paths found in the JSON structure. Dictionary
            keys use dot notation (e.g., "config.database"), array indices use bracket
            notation (e.g., "items[0]"). Empty list for primitive values.

        Notes
        -----
        This function is part of JSON key extraction for config file indexing. It
        recursively traverses nested structures to build a flat list of all accessible
        key paths. Time complexity: O(n) where n is the total number of keys and array
        elements in the structure. The function handles circular references gracefully
        by only traversing each structure once (no cycles in JSON). Thread-safe as it
        operates on immutable input data.
        """
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
