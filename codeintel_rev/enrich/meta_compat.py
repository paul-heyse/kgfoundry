"""Helpers for reading module metadata payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "definition_entries",
    "export_names_from_meta",
    "has_dunder_all",
    "import_entries",
    "imported_modules",
    "meta_payload",
]


def meta_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the ``meta`` payload for ``row`` or an empty mapping.

    Returns
    -------
    Mapping[str, Any]
        Meta dictionary when present, otherwise an empty mapping.
    """
    meta = row.get("meta")
    return meta if isinstance(meta, Mapping) else {}


def import_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return normalized import dictionaries derived from the meta payload.

    Returns
    -------
    list[dict[str, Any]]
        Normalized import dictionaries describing module, names, aliases, star flags,
        and relative levels. Returns an empty list when meta imports are missing.
    """
    meta = meta_payload(row)
    return _normalize_imports(meta.get("legacy_imports"))


def definition_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return normalized definition dictionaries derived from meta.

    Returns
    -------
    list[dict[str, Any]]
        Normalized dictionaries describing definitions captured during analysis
        (name, kind, and optional line number). Empty list when no metadata present.
    """
    meta = meta_payload(row)
    return _normalize_definitions(meta.get("definitions"))


def export_names_from_meta(row: Mapping[str, Any]) -> list[str]:
    """Return export symbol names derived from meta payloads.

    Returns
    -------
    list[str]
        Sorted, deduplicated export names favoring ``__all__`` entries when present.
    """
    meta = meta_payload(row)
    exports = meta.get("exports")
    names: list[str] = []
    if isinstance(exports, list):
        via_dunder = [entry for entry in exports if _truthy(entry, "via_dunder_all")]
        source = via_dunder if via_dunder else exports
        for entry in source:
            name = entry.get("name") if isinstance(entry, Mapping) else None
            if isinstance(name, str) and not (not via_dunder and name.startswith("_")):
                names.append(name)
    if names:
        return sorted(set(names))
    return []


def imported_modules(row: Mapping[str, Any]) -> list[str]:
    """Return sorted module names imported by ``row``.

    Returns
    -------
    list[str]
        Sorted unique module names referenced in the meta imports array.
    """
    meta = meta_payload(row)
    imports_meta = meta.get("imports")
    modules: list[str] = []
    if isinstance(imports_meta, list):
        for entry in imports_meta:
            if not isinstance(entry, Mapping):
                continue
            dst = entry.get("dst_module")
            if isinstance(dst, str) and dst:
                modules.append(dst)
    if modules:
        return sorted(set(modules))
    return []


def has_dunder_all(row: Mapping[str, Any]) -> bool:
    """Return True if meta payload declares ``__all__`` exports.

    Returns
    -------
    bool
        ``True`` when at least one export entry is flagged via ``__all__``.
    """
    meta = meta_payload(row)
    exports = meta.get("exports")
    if isinstance(exports, list):
        return any(isinstance(entry, Mapping) and entry.get("via_dunder_all") for entry in exports)
    return False


def _normalize_imports(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence):
        return []
    results: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        module = entry.get("module")
        names = entry.get("names") or []
        aliases_obj = entry.get("aliases")
        alias_items = aliases_obj.items() if isinstance(aliases_obj, Mapping) else []
        is_star = bool(entry.get("is_star"))
        level = int(entry.get("level") or 0)
        results.append(
            {
                "module": module if isinstance(module, str) or module is None else str(module),
                "names": [str(name) for name in names if isinstance(name, str)],
                "aliases": {
                    str(k): str(v)
                    for k, v in alias_items
                    if isinstance(k, str) and isinstance(v, str)
                },
                "is_star": is_star,
                "level": level,
            }
        )
    return results


def _normalize_definitions(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence):
        return []
    results: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        kind = entry.get("kind")
        lineno = entry.get("lineno")
        if not isinstance(name, str) or not isinstance(kind, str):
            continue
        normalized = {"name": name, "kind": kind}
        if isinstance(lineno, int):
            normalized["lineno"] = lineno
        results.append(normalized)
    return results


def _truthy(entry: Mapping[str, Any], key: str) -> bool:
    value = entry.get(key)
    return bool(value)
