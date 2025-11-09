"""Legacy errors module - redirects to new error hierarchy.

This module maintains backward compatibility by re-exporting exceptions
from the new structured error hierarchy. New code should import directly
from kgfoundry_common.errors.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.errors.exceptions import (
    CatalogLoadError,
    ChunkingError,
    DoclingError,
    DownloadError,
    EmbeddingError,
    IndexBuildError,
    LinkerCalibrationError,
    Neo4jError,
    OCRTimeoutError,
    OntologyParseError,
    SpladeOOMError,
    SymbolAttachmentError,
    UnsupportedMIMEError,
)
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "CatalogLoadError",
    "ChunkingError",
    "DoclingError",
    "DownloadError",
    "EmbeddingError",
    "IndexBuildError",
    "LinkerCalibrationError",
    "Neo4jError",
    "OCRTimeoutError",
    "OntologyParseError",
    "SpladeOOMError",
    "SymbolAttachmentError",
    "UnsupportedMIMEError",
]

__navmap__ = load_nav_metadata(__name__, tuple(__all__))
