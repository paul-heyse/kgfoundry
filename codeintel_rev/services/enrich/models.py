"""Typed records used by the refactored enrich services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    """Lightweight module metadata emitted by the CLI commands.

    Attributes
    ----------
    path : Path
        File path relative to repository root.
    module : str
        Python module name (e.g., "module.submodule").
    language : str
        Programming language identifier (e.g., "python", "typescript").
    loc : int
        Lines of code count for this module. Must be non-negative.
    tags : tuple[str, ...]
        Tuple of tags inferred for this module (e.g., ("cli", "test")).
    meta : Mapping[str, Any], optional
        Additional metadata dictionary. Empty dictionary if no additional
        metadata. Defaults to empty dictionary.
    """

    path: Path
    module: str
    language: str
    loc: int
    tags: tuple[str, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Paths to the artifacts emitted by ``run_all_exports``.

    Attributes
    ----------
    modules_jsonl : Path
        Path to the modules JSONL file containing module records.
    repo_map : Path
        Path to the repository map file.
    tag_index : Path
        Path to the tag index file.
    markdown_dir : Path
        Directory path containing markdown module documentation.
    """

    modules_jsonl: Path
    repo_map: Path
    tag_index: Path
    markdown_dir: Path


__all__ = ["ExportResult", "ModuleRecord"]
