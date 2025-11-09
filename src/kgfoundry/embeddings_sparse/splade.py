"""Expose ``embeddings_sparse.splade`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from embeddings_sparse.splade import (
    LuceneImpactIndex,
    PureImpactIndex,
    SPLADEv3Encoder,
    get_splade,
)
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "LuceneImpactIndex",
    "PureImpactIndex",
    "SPLADEv3Encoder",
    "get_splade",
]

__navmap__ = load_nav_metadata(__name__, tuple(__all__))
