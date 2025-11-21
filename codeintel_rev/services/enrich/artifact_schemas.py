# SPDX-License-Identifier: MIT
"""Lightweight schemas for analytics artifacts emitted by the pipeline."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CoverageRowModel(BaseModel):
    """Schema for coverage.jsonl rows."""

    path: str
    covered_lines_ratio: float = Field(default=0.0, ge=0.0)
    covered_defs_ratio: float = Field(default=0.0, ge=0.0)

    model_config = ConfigDict(extra="allow")


class HotspotRowModel(BaseModel):
    """Schema for hotspots.jsonl rows."""

    path: str
    hotspot_score: float = 0.0
    fan_in: int = 0
    fan_out: int = 0
    type_error_count: int = Field(default=0, ge=0)
    used_by_files: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="allow")


class ConfigRecordModel(BaseModel):
    """Schema for config_index.json entries."""

    path: str
    references: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class TagIndexModel(RootModel[Mapping[str, list[str]]]):
    """Root model representing the tag index mapping."""

    root: Mapping[str, list[str]]


class TagCountsModel(RootModel[Mapping[str, int]]):
    """Root model representing tag counts."""

    root: Mapping[str, int]


class DocHealthRowModel(BaseModel):
    """Schema for doc health records."""

    path: str
    docstring: str | None = None
    doc_has_summary: bool | None = None
    doc_param_parity: bool | None = None
    doc_examples_present: bool | None = None

    model_config = ConfigDict(extra="allow")


class FunctionMetricRowModel(BaseModel):
    """Minimal schema for function metrics rows."""

    function_goid_h128: str | int | float
    urn: str
    rel_path: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    loc: int
    cyclomatic_complexity: int

    model_config = ConfigDict(extra="allow")


class FunctionTypeRowModel(BaseModel):
    """Minimal schema for function typedness rows."""

    function_goid_h128: str | int | float
    urn: str
    rel_path: str
    qualname: str
    total_params: int
    annotated_params: int
    param_typed_ratio: float
    typedness_bucket: str

    model_config = ConfigDict(extra="allow")


class AnnotationRatioModel(BaseModel):
    """Schema for annotation ratio payloads."""

    params: float | None = None
    returns: float | None = None

    model_config = ConfigDict(extra="allow")


class TypednessRowModel(BaseModel):
    """Schema for typedness summary rows."""

    path: str
    type_error_count: int = Field(default=0, ge=0)
    annotation_ratio: AnnotationRatioModel | float | None = None
    untyped_defs: int | None = None
    overlay_needed: bool = False

    model_config = ConfigDict(extra="allow")


class PromotedEntryModel(BaseModel):
    """Schema for a promoted artifact record."""

    source: str
    dest: str

    model_config = ConfigDict(extra="allow")


class PromotedIndexModel(RootModel[list[PromotedEntryModel]]):
    """Root model for promoted artifact index."""

    root: list[PromotedEntryModel]


__all__ = [
    "AnnotationRatioModel",
    "ConfigRecordModel",
    "CoverageRowModel",
    "DocHealthRowModel",
    "FunctionMetricRowModel",
    "FunctionTypeRowModel",
    "HotspotRowModel",
    "PromotedEntryModel",
    "PromotedIndexModel",
    "TagCountsModel",
    "TagIndexModel",
    "TypednessRowModel",
]
