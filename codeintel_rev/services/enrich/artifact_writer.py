# SPDX-License-Identifier: MIT
"""Helpers for writing and aliasing graph artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from codeintel_rev.services.enrich.artifact_schemas import (
    ConfigRecordModel,
    CoverageRowModel,
    HotspotRowModel,
    TagIndexModel,
)
from codeintel_rev.services.enrich.artifacts import GraphArtifactPaths
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.graph_steps import build_graph_manifest
from codeintel_rev.services.enrich.io import write_parquet_to_jsonl

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None

JsonModelT = TypeVar("JsonModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ArtifactWriter:
    """Persist graph artifacts and optional aliases."""

    manifest: GraphArtifactPaths

    def promote_aliases(self) -> None:
        """Promote legacy aliases for import/use graphs if present."""
        if self.manifest.import_edges:
            legacy = self.manifest.import_edges.parent / "imports.parquet"
            self._copy_if_missing(self.manifest.import_edges, legacy)
        if self.manifest.symbol_use_edges:
            legacy = self.manifest.symbol_use_edges.parent / "uses.parquet"
            self._copy_if_missing(self.manifest.symbol_use_edges, legacy)

    def emit_jsonl_sidecars(self) -> None:
        """Emit JSONL sidecars for Parquet artifacts where applicable."""
        for parquet_path in (
            self.manifest.import_edges,
            self.manifest.symbol_use_edges,
            self.manifest.call_nodes,
            self.manifest.call_edges,
            self.manifest.cfg_blocks,
            self.manifest.cfg_edges,
            self.manifest.dfg_edges,
            self.manifest.goids,
            self.manifest.goid_xwalk,
        ):
            if parquet_path is None:
                continue
            if not parquet_path.exists():
                continue
            jsonl_path = parquet_path.with_suffix(".jsonl")
            write_parquet_to_jsonl(parquet_path, jsonl_path)

    @staticmethod
    def _copy_if_missing(source: Path, dest: Path) -> None:
        if not source.exists():
            return
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def build_writer(ctx: PipelineContext) -> ArtifactWriter:
    """Build a writer using the context's data directory.

    Returns
    -------
    ArtifactWriter
        Writer bound to the context's artifact manifest.
    """
    manifest = build_graph_manifest(ctx)
    return ArtifactWriter(manifest=manifest)


def manifest_from_dir(base_dir: Path) -> GraphArtifactPaths:
    """Construct a manifest directly from a base output directory.

    Returns
    -------
    GraphArtifactPaths
        Manifest with expected graph/AST artifact locations.
    """
    graphs_dir = base_dir / "graphs"
    goid_dir = base_dir / "goid"
    ast_dir = base_dir / "ast"
    return GraphArtifactPaths(
        goids=goid_dir / "goids.parquet",
        goid_xwalk=goid_dir / "goid_xwalk.parquet",
        call_nodes=graphs_dir / "call_nodes.parquet",
        call_edges=graphs_dir / "call_edges.parquet",
        cfg_blocks=graphs_dir / "cfg_blocks.parquet",
        cfg_edges=graphs_dir / "cfg_edges.parquet",
        dfg_edges=graphs_dir / "dfg_edges.parquet",
        import_edges=graphs_dir / "import_graph_edges.parquet",
        symbol_use_edges=graphs_dir / "symbol_use_edges.parquet",
        ast_nodes=ast_dir / "ast_nodes.parquet",
        ast_metrics=ast_dir / "ast_metrics.parquet",
        ast_dir=ast_dir,
    )


def process_artifact_dir(base_dir: Path) -> None:
    """Apply alias promotion and JSONL emission for graph artifacts under ``base_dir``."""
    writer = ArtifactWriter(manifest=manifest_from_dir(base_dir))
    writer.promote_aliases()
    writer.emit_jsonl_sidecars()
    ArtifactValidator(base_dir).validate()


class ArtifactValidator:
    """Validate emitted analytics artifacts against permissive schemas."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def validate(self) -> None:
        """Validate analytics artifacts if present."""
        analytics_dir = self.root / "analytics"
        self._validate_jsonl(analytics_dir / "coverage.jsonl", CoverageRowModel)
        self._validate_jsonl(analytics_dir / "hotspots.jsonl", HotspotRowModel)
        self._validate_json(analytics_dir / "config_index.json", ConfigRecordModel)
        self._validate_tags_yaml(self.root / "tags" / "tags_index.yaml")

    @staticmethod
    def _validate_jsonl(path: Path, model: type[JsonModelT]) -> None:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                message = f"Invalid JSON in {path}: {exc}"
                raise RuntimeError(message) from exc
            model.model_validate(payload)

    @staticmethod
    def _validate_json(path: Path, model: type[JsonModelT]) -> None:
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for entry in payload:
                model.model_validate(entry)
            return
        model.model_validate(payload)

    @staticmethod
    def _validate_tags_yaml(path: Path) -> None:
        if yaml_module is None or not path.exists():
            return
        load_fn = getattr(yaml_module, "safe_load", None)
        if not callable(load_fn):
            return
        payload = load_fn(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            message = f"tags_index.yaml must contain a mapping. Found: {type(payload)!r}"
            raise TypeError(message)
        TagIndexModel.model_validate(payload)


__all__ = ["ArtifactWriter", "build_writer"]
