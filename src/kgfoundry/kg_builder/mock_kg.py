"""Expose ``kg_builder.mock_kg`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kg_builder.mock_kg import MockKG
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "MockKG",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
