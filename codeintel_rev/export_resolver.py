# SPDX-License-Identifier: MIT
"""Resolve exports and re-exports for module records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from codeintel_rev.module_utils import (
    import_targets_for_entry,
    module_name_candidates,
    normalize_module_name,
)

EXPORT_HUB_THRESHOLD = 10


def build_module_name_map(
    rows: Sequence[Mapping[str, Any]],
    package_prefix: str | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Return mapping of module name → module row for quick lookup.

    Parameters
    ----------
    rows : list[dict[str, Any]]
        Module metadata rows to index by module name.
    package_prefix : str | None, optional
        Optional package prefix for module name normalization.

    Returns
    -------
    dict[str, dict[str, Any]]
        Mapping of dotted module names to the associated row dictionaries.
    """
    mapping: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for candidate in module_name_candidates(row["path"], package_prefix):
            if candidate:
                mapping[candidate] = row
    return mapping


def resolve_exports(
    row: Mapping[str, Any],
    modules_by_name: Mapping[str, Mapping[str, Any]],
    *,
    package_prefix: str | None = None,
) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """Return exports resolved from star-imports and re-export metadata.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row containing imports and definitions.
    modules_by_name : Mapping[str, Mapping[str, Any]]
        Mapping of module names to their row dictionaries.
    package_prefix : str | None, optional
        Optional package prefix for module name resolution.

    Returns
    -------
    tuple[dict[str, list[str]], dict[str, dict[str, str]]]
        Pair of ``exports_resolved`` mapping and ``reexports`` metadata.
    """
    resolved: dict[str, list[str]] = {}
    reexports: dict[str, dict[str, str]] = {}
    current_module = normalize_module_name(row["path"])

    for imp in row.get("imports", []) or []:
        if not isinstance(imp, Mapping) or not imp.get("is_star"):
            continue
        module = imp.get("module")
        level = int(imp.get("level") or 0)
        names = imp.get("names") or []
        if not isinstance(names, list):
            names = []
        for target in import_targets_for_entry(current_module, module, [], level):
            origin_row = modules_by_name.get(target)
            if not origin_row and package_prefix:
                prefixed = f"{package_prefix}.{target}" if target else package_prefix
                origin_row = modules_by_name.get(prefixed)
            if not origin_row:
                continue
            export_names = _public_names(origin_row)
            if not export_names:
                continue
            resolved[target] = sorted(export_names)
            local_defs = {definition.get("name") for definition in row.get("defs") or []}
            for name in export_names:
                if name in local_defs:
                    continue
                reexports.setdefault(name, {"from": target, "symbol": f"{target}.{name}"})
    return resolved, reexports


def is_reexport_hub(row: Mapping[str, Any]) -> bool:
    """Return True when a module behaves like a re-export hub.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row containing exports and imports metadata.

    Returns
    -------
    bool
        True when the module is considered a re-export hub.
    """
    exports = row.get("exports") or []
    imports = row.get("imports") or []
    has_star = any(entry.get("is_star") for entry in imports if isinstance(entry, Mapping))
    return bool(has_star) or (isinstance(exports, list) and len(exports) >= EXPORT_HUB_THRESHOLD)


def _public_names(row: Mapping[str, Any]) -> list[str]:
    exports = row.get("exports") or []
    if isinstance(exports, list) and exports:
        return [name for name in exports if isinstance(name, str)]
    names: list[str] = []
    for definition in row.get("defs") or []:
        if not isinstance(definition, Mapping):
            continue
        kind = definition.get("kind")
        name = definition.get("name")
        if (
            isinstance(name, str)
            and isinstance(kind, str)
            and kind in {"function", "class"}
            and not name.startswith("_")
        ):
            names.append(name)
    return names
