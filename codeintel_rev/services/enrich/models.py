"""Typed records used by the refactored enrich services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    """Lightweight module metadata emitted by the CLI commands."""

    path: Path
    module: str
    language: str
    loc: int
    tags: tuple[str, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Paths to the artifacts emitted by ``run_all_exports``."""

    modules_jsonl: Path
    repo_map: Path
    tag_index: Path
    markdown_dir: Path


__all__ = ["ExportResult", "ModuleRecord"]
