"""Public helpers for kgfoundry namespace bridge packages."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry.tooling_bridge import (
    namespace_attach,
    namespace_dir,
    namespace_exports,
    namespace_getattr,
)
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "namespace_attach",
    "namespace_dir",
    "namespace_exports",
    "namespace_getattr",
]

__navmap__ = load_nav_metadata(__name__, tuple(__all__))
