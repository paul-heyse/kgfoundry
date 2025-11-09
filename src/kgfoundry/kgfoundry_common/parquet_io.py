"""Expose ``kgfoundry_common.parquet_io`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.parquet_io import ParquetChunkWriter, ParquetVectorWriter

__all__ = [
    "ParquetChunkWriter",
    "ParquetVectorWriter",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
