"""Expose ``registry.helper`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata
from registry.helper import DuckDBRegistryHelper

__all__ = [
    "DuckDBRegistryHelper",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
