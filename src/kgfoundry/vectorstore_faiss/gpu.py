"""Expose ``vectorstore_faiss.gpu`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata
from vectorstore_faiss.gpu import (
    FaissGpuIndex,
    FloatArray,
    IntArray,
    StrArray,
    VecArray,
)

__all__ = [
    "FaissGpuIndex",
    "FloatArray",
    "IntArray",
    "StrArray",
    "VecArray",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
