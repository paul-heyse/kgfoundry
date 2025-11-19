"""Helpers for reading module metadata payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from codeintel_rev.enrich.types import DocInfo, ExportItem, ImportEdge, ModuleMetrics

__all__ = [
    "DefinitionRecord",
    "ImportRecord",
    "ModuleMeta",
    "definition_entries",
    "export_names_from_meta",
    "has_dunder_all",
    "import_entries",
    "imported_modules",
    "meta_payload",
    "module_meta",
]


def meta_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the ``meta`` payload for ``row`` or an empty mapping.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing metadata.

    Returns
    -------
    Mapping[str, Any]
        Meta dictionary when present, otherwise an empty mapping.
    """
    meta = row.get("meta")
    return meta if isinstance(meta, Mapping) else {}


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """Immutable import record with module, names, aliases, and relative level.

    Attributes
    ----------
    module : str | None
        Imported module name. None for relative imports without explicit module.
    names : tuple[str, ...]
        Tuple of imported symbol names.
    aliases : dict[str, str]
        Dictionary mapping original names to their aliases.
    is_star : bool
        Whether this is a star import (from module import *).
    level : int
        Relative import level (0 for absolute imports).
    """

    module: str | None
    names: tuple[str, ...]
    aliases: dict[str, str]
    is_star: bool
    level: int

    def to_dict(self) -> dict[str, Any]:
        """Convert import record to dictionary.

        Returns
        -------
        dict[str, Any]
            Dictionary representation of the import record.
        """
        return {
            "module": self.module,
            "names": list(self.names),
            "aliases": dict(self.aliases),
            "is_star": self.is_star,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    """Immutable definition record with name, kind, and optional line number.

    Attributes
    ----------
    name : str
        Definition name (function, class, or variable name).
    kind : str
        Definition kind identifier (e.g., "function", "class", "variable").
    lineno : int | None
        Line number where the definition occurs. None if line number is unavailable.
    """

    name: str
    kind: str
    lineno: int | None

    def to_dict(self) -> dict[str, Any]:
        """Convert definition record to dictionary.

        Returns
        -------
        dict[str, Any]
            Dictionary representation of the definition record.
        """
        payload: dict[str, Any] = {"name": self.name, "kind": self.kind}
        if self.lineno is not None:
            payload["lineno"] = self.lineno
        return payload


def import_entries(row: Mapping[str, Any]) -> list[ImportRecord]:
    """Return normalized import records derived from the meta payload.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing import metadata.

    Returns
    -------
    list[ImportRecord]
        Normalized import records describing module, names, aliases, star flags,
        and relative levels. Returns an empty list when meta imports are missing.
    """
    meta = meta_payload(row)
    return _normalize_imports(meta.get("legacy_imports"))


def definition_entries(row: Mapping[str, Any]) -> list[DefinitionRecord]:
    """Return normalized definition records derived from meta.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing definition metadata.

    Returns
    -------
    list[DefinitionRecord]
        Normalized definition records describing name, kind, and optional line number.
        Empty list when no metadata present.
    """
    meta = meta_payload(row)
    return _normalize_definitions(meta.get("definitions"))


@dataclass(frozen=True, slots=True)
class ModuleMeta:
    """Typed representation of the serialized module metadata payload."""

    module: str
    path: str
    imports: tuple[ImportEdge, ...]
    exports: tuple[ExportItem, ...]
    docs: DocInfo
    metrics: ModuleMetrics
    definitions: tuple[DefinitionRecord, ...]
    legacy_imports: tuple[ImportRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping.

        Returns
        -------
        dict[str, Any]
            Dictionary suitable for serialization.
        """
        return {
            "module": self.module,
            "path": self.path,
            "imports": [edge.__dict__ for edge in self.imports],
            "exports": [item.__dict__ for item in self.exports],
            "docs": {
                "module_docstring": self.docs.module_docstring,
                "module_has_doc": self.docs.module_has_doc,
                "classes_with_doc": self.docs.classes_with_doc,
                "classes_total": self.docs.classes_total,
                "functions_with_doc": self.docs.functions_with_doc,
                "functions_total": self.docs.functions_total,
            },
            "metrics": {
                "module": self.metrics.module,
                "annotated_defs": self.metrics.annotated_defs,
                "defs_total": self.metrics.defs_total,
                "annotation_ratio": self.metrics.annotation_ratio,
                "has_top_level_side_effects": self.metrics.has_top_level_side_effects,
            },
            "definitions": [record.to_dict() for record in self.definitions],
            "legacy_imports": [record.to_dict() for record in self.legacy_imports],
        }

    @classmethod
    def from_mapping(cls, meta: Mapping[str, Any]) -> ModuleMeta:
        """Construct ModuleMeta from a serialized mapping.

        Parameters
        ----------
        meta : Mapping[str, Any]
            Serialized meta payload.

        Returns
        -------
        ModuleMeta
            Parsed module metadata.
        """
        module = str(meta.get("module") or "")
        path = str(meta.get("path") or "")
        imports = tuple(
            _deserialize_edge(entry)
            for entry in meta.get("imports", [])
            if isinstance(entry, Mapping)
        )
        exports = tuple(
            _deserialize_export(entry)
            for entry in meta.get("exports", [])
            if isinstance(entry, Mapping)
        )
        docs = _deserialize_docs(meta.get("docs") or {})
        metrics = _deserialize_metrics(meta.get("metrics") or {})
        definitions = tuple(_normalize_definitions(meta.get("definitions")))
        legacy = tuple(_normalize_imports(meta.get("legacy_imports")))
        return cls(
            module=module,
            path=path,
            imports=imports,
            exports=exports,
            docs=docs,
            metrics=metrics,
            definitions=definitions,
            legacy_imports=legacy,
        )


def module_meta(row: Mapping[str, Any]) -> ModuleMeta | None:
    """Return ModuleMeta for ``row`` when available.

    Parameters
    ----------
    row : Mapping[str, Any]
        Row dictionary containing module metadata.

    Returns
    -------
    ModuleMeta | None
        Parsed meta payload when present, otherwise None.
    """
    meta = row.get("meta")
    if not isinstance(meta, Mapping):
        return None
    return ModuleMeta.from_mapping(meta)


def export_names_from_meta(row: Mapping[str, Any]) -> list[str]:
    """Return export symbol names derived from meta payloads.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing export metadata.

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

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing import metadata.

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

    Parameters
    ----------
    row : Mapping[str, Any]
        Module row dictionary containing export metadata.

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


def _normalize_imports(value: object) -> list[ImportRecord]:
    if not isinstance(value, Sequence):
        return []
    results: list[ImportRecord] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        module = entry.get("module")
        names = entry.get("names") or []
        aliases_obj = entry.get("aliases")
        alias_items = aliases_obj.items() if isinstance(aliases_obj, Mapping) else []
        is_star = bool(entry.get("is_star"))
        level = int(entry.get("level") or 0)
        normalized_aliases = {
            k: v for k, v in alias_items if isinstance(k, str) and isinstance(v, str)
        }
        normalized_names = tuple(str(name) for name in names if isinstance(name, str))
        normalized_module = module if isinstance(module, str) or module is None else str(module)
        results.append(
            ImportRecord(
                module=normalized_module,
                names=normalized_names,
                aliases=normalized_aliases,
                is_star=is_star,
                level=level,
            )
        )
    return results


def _normalize_definitions(value: object) -> list[DefinitionRecord]:
    if not isinstance(value, Sequence):
        return []
    results: list[DefinitionRecord] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        kind = entry.get("kind")
        lineno = entry.get("lineno")
        if not isinstance(name, str) or not isinstance(kind, str):
            continue
        normalized_lineno = lineno if isinstance(lineno, int) else None
        results.append(DefinitionRecord(name=name, kind=kind, lineno=normalized_lineno))
    return results


def _truthy(entry: Mapping[str, Any], key: str) -> bool:
    value = entry.get(key)
    return bool(value)


def _deserialize_edge(entry: Mapping[str, Any]) -> ImportEdge:
    return ImportEdge(
        src_module=str(entry.get("src_module") or ""),
        dst_module=str(entry.get("dst_module") or ""),
        alias=entry.get("alias"),
        level=int(entry.get("level") or 0),
    )


def _deserialize_export(entry: Mapping[str, Any]) -> ExportItem:
    return ExportItem(
        module=str(entry.get("module") or ""),
        name=str(entry.get("name") or ""),
        kind=str(entry.get("kind") or ""),
        via_dunder_all=bool(entry.get("via_dunder_all")),
    )


def _deserialize_docs(data: Mapping[str, Any]) -> DocInfo:
    return DocInfo(
        module=str(data.get("module") or ""),
        module_docstring=data.get("module_docstring"),
        module_has_doc=bool(data.get("module_has_doc")),
        classes_with_doc=int(data.get("classes_with_doc") or 0),
        classes_total=int(data.get("classes_total") or 0),
        functions_with_doc=int(data.get("functions_with_doc") or 0),
        functions_total=int(data.get("functions_total") or 0),
    )


def _deserialize_metrics(data: Mapping[str, Any]) -> ModuleMetrics:
    return ModuleMetrics(
        module=str(data.get("module") or ""),
        annotated_defs=int(data.get("annotated_defs") or 0),
        defs_total=int(data.get("defs_total") or 0),
        annotation_ratio=float(data.get("annotation_ratio") or 0.0),
        has_top_level_side_effects=bool(data.get("has_top_level_side_effects")),
    )
