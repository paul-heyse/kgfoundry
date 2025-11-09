"""Expose ``embeddings_sparse.base`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from embeddings_sparse.base import SparseEncoder, SparseIndex
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "SparseEncoder",
    "SparseIndex",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
