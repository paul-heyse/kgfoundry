"""Overview of linker.

This module bundles linker logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "Linker",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor Linker]
class Linker:
    """Placeholder class for linking orchestration and scoring.

    This class serves as a placeholder for future linking functionality that orchestrates concept
    linking and scoring operations. Implementation details will be added later.
    """
