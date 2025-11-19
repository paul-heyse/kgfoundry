"""Typed records emitted by the LibCST analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """Graph edge representing a resolved import relationship."""

    src_module: str
    dst_module: str
    alias: str | None
    level: int


@dataclass(frozen=True, slots=True)
class ExportItem:
    """Metadata describing a single exported symbol."""

    module: str
    name: str
    kind: str
    via_dunder_all: bool


@dataclass(frozen=True, slots=True)
class DocInfo:
    """Docstring statistics for a module + its top-level symbols."""

    module: str
    module_docstring: str | None
    module_has_doc: bool
    classes_with_doc: int
    classes_total: int
    functions_with_doc: int
    functions_total: int


@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    """Lightweight metrics describing annotation coverage and side effects."""

    module: str
    annotated_defs: int
    defs_total: int
    annotation_ratio: float
    has_top_level_side_effects: bool


@dataclass(frozen=True, slots=True)
class DefinitionInfo:
    """Summary of a top-level definition captured during traversal."""

    module: str
    name: str
    kind: str
    lineno: int | None


@dataclass(frozen=True, slots=True)
class LegacyImportRecord:
    """Structured import metadata used by legacy consumers."""

    module: str | None
    names: tuple[str, ...]
    aliases: dict[str, str]
    is_star: bool
    level: int


@dataclass(frozen=True, slots=True)
class ModuleAnalysis:
    """Aggregate LibCST analysis output used by enrichment."""

    path: Path
    module: str
    imports: list[ImportEdge]
    exports: list[ExportItem]
    dunder_all: tuple[str, ...]
    docs: DocInfo
    metrics: ModuleMetrics
    definitions: list[DefinitionInfo]
    legacy_imports: list[LegacyImportRecord]
