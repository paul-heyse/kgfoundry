"""Overview of vlm.

This module bundles vlm logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "GraniteDoclingVLM",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor GraniteDoclingVLM]
class GraniteDoclingVLM:
    """Placeholder class for vision-language model tagging helpers.

    This class serves as a placeholder for future Granite vision-language model integration for
    docling_kg document processing. Implementation details will be added later.
    """
