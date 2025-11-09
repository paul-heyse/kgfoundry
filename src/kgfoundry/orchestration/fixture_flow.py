"""Expose ``orchestration.fixture_flow`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata
from orchestration.fixture_flow import (
    fixture_pipeline,
    t_prepare_dirs,
    t_register_in_duckdb,
    t_write_fixture_chunks,
    t_write_fixture_dense,
    t_write_fixture_splade,
)

__all__ = [
    "fixture_pipeline",
    "t_prepare_dirs",
    "t_register_in_duckdb",
    "t_write_fixture_chunks",
    "t_write_fixture_dense",
    "t_write_fixture_splade",
]

__navmap__ = load_nav_metadata(__name__, tuple(__all__))
