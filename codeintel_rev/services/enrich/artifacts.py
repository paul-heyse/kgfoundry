# SPDX-License-Identifier: MIT
"""Shared artifact manifest/writer helpers for enrichment graphs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GraphArtifactPaths:
    """Normalized graph artifact locations."""

    goids: Path | None = None
    goid_xwalk: Path | None = None
    call_nodes: Path | None = None
    call_edges: Path | None = None
    cfg_blocks: Path | None = None
    cfg_edges: Path | None = None
    dfg_edges: Path | None = None
    import_edges: Path | None = None
    symbol_use_edges: Path | None = None
    ast_nodes: Path | None = None
    ast_metrics: Path | None = None
    ast_dir: Path | None = None


class ArtifactWriter(Protocol):
    """Protocol for artifact writers that emit a manifest of paths."""

    def write(self, out_dir: Path) -> GraphArtifactPaths:
        """Persist artifacts into ``out_dir`` and return their paths."""
        ...


__all__ = ["ArtifactWriter", "GraphArtifactPaths"]
