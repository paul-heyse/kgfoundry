# SPDX-License-Identifier: MIT
"""Schema validation helpers for enrichment rows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModuleRecordModel"]


class ModuleRecordModel(BaseModel):
    """Lightweight schema used to validate modules.jsonl rows."""

    model_config = ConfigDict(extra="allow")

    path: str
    docstring: str | None = None
    doc_summary: str | None = None
    imports: list[dict[str, Any]] = Field(default_factory=list)
    defs: list[dict[str, Any]] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    exports_declared: list[str] = Field(default_factory=list)
    outline_nodes: list[dict[str, Any]] = Field(default_factory=list)
    scip_symbols: list[str] = Field(default_factory=list)
    parse_ok: bool = True
    errors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    type_errors: int = 0
    type_error_count: int = 0
    repo_path: str | None = None
    module_name: str | None = None
    stable_id: str | None = None
    doc_has_summary: bool = True
    doc_param_parity: bool = True
    doc_examples_present: bool = False
    doc_metrics: dict[str, Any] = Field(default_factory=dict)
    doc_items: list[dict[str, Any]] = Field(default_factory=list)
    annotation_ratio: dict[str, Any] = Field(default_factory=dict)
    untyped_defs: int = 0
    side_effects: dict[str, Any] = Field(default_factory=dict)
    raises: list[str] = Field(default_factory=list)
    complexity: dict[str, Any] = Field(default_factory=dict)
    covered_lines_ratio: float = 0.0
    covered_defs_ratio: float = 0.0
    config_refs: list[str] = Field(default_factory=list)
    overlay_needed: bool = False
