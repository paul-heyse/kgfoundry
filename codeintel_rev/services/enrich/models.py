# SPDX-License-Identifier: MIT
"""Service-level enrichment models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.enrich.models import ModuleRecord


@dataclass(slots=True, frozen=True)
class ExportArtifacts:
    """Selected export targets produced by the enrichment pipeline."""

    modules_jsonl: Path
    repo_map: Path
    tag_index: Path
    markdown_dir: Path


__all__ = ["ExportArtifacts", "ModuleRecord"]
