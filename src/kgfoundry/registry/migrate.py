"""Expose ``registry.migrate`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata
from registry.migrate import apply, main

__all__ = [
    "apply",
    "main",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
