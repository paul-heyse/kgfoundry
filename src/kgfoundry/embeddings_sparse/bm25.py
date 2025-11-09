"""Expose ``embeddings_sparse.bm25`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from embeddings_sparse.bm25 import BM25Doc, LuceneBM25, PurePythonBM25, get_bm25
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "BM25Doc",
    "LuceneBM25",
    "PurePythonBM25",
    "get_bm25",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
