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


__all__ = [
    "ConfigRecordModel",
    "CoverageRowModel",
    "HotspotRowModel",
    "TagIndexModel",
]
