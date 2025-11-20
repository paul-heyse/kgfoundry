"""Typed records used by the refactored enrich services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.enrich.models import ModuleRecord


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
