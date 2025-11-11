"""Storage and external service adapters for CodeIntel MCP."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "BM25CorpusMetadata",
    "BM25CorpusSummary",
    "BM25IndexManager",
    "BM25IndexMetadata",
    "HybridResultDoc",
    "HybridSearchEngine",
    "HybridSearchResult",
    "SpladeArtifactMetadata",
    "SpladeArtifactsManager",
    "SpladeBenchmarkOptions",
    "SpladeBenchmarkSummary",
    "SpladeBuildOptions",
    "SpladeEncodeOptions",
    "SpladeEncodingMetadata",
    "SpladeEncodingSummary",
    "SpladeExportOptions",
    "SpladeExportSummary",
    "SpladeIndexManager",
    "SpladeIndexMetadata",
]

if TYPE_CHECKING:  # pragma: no cover - import-time heavy modules avoided at runtime
    from codeintel_rev.io.bm25_manager import (
        BM25CorpusMetadata,
        BM25CorpusSummary,
        BM25IndexManager,
        BM25IndexMetadata,
    )
    from codeintel_rev.io.hybrid_search import (
        HybridResultDoc,
        HybridSearchEngine,
        HybridSearchResult,
    )
    from codeintel_rev.io.splade_manager import (
        SpladeArtifactMetadata,
        SpladeArtifactsManager,
        SpladeBenchmarkOptions,
        SpladeBenchmarkSummary,
        SpladeBuildOptions,
        SpladeEncodeOptions,
        SpladeEncodingMetadata,
        SpladeEncodingSummary,
        SpladeExportOptions,
        SpladeExportSummary,
        SpladeIndexManager,
        SpladeIndexMetadata,
    )

_EXPORTS: dict[str, tuple[str, str]] = {
    "BM25CorpusMetadata": ("codeintel_rev.io.bm25_manager", "BM25CorpusMetadata"),
    "BM25CorpusSummary": ("codeintel_rev.io.bm25_manager", "BM25CorpusSummary"),
    "BM25IndexManager": ("codeintel_rev.io.bm25_manager", "BM25IndexManager"),
    "BM25IndexMetadata": ("codeintel_rev.io.bm25_manager", "BM25IndexMetadata"),
    "HybridResultDoc": ("codeintel_rev.io.hybrid_search", "HybridResultDoc"),
    "HybridSearchEngine": ("codeintel_rev.io.hybrid_search", "HybridSearchEngine"),
    "HybridSearchResult": ("codeintel_rev.io.hybrid_search", "HybridSearchResult"),
    "SpladeArtifactMetadata": ("codeintel_rev.io.splade_manager", "SpladeArtifactMetadata"),
    "SpladeArtifactsManager": ("codeintel_rev.io.splade_manager", "SpladeArtifactsManager"),
    "SpladeBenchmarkOptions": ("codeintel_rev.io.splade_manager", "SpladeBenchmarkOptions"),
    "SpladeBenchmarkSummary": ("codeintel_rev.io.splade_manager", "SpladeBenchmarkSummary"),
    "SpladeBuildOptions": ("codeintel_rev.io.splade_manager", "SpladeBuildOptions"),
    "SpladeEncodeOptions": ("codeintel_rev.io.splade_manager", "SpladeEncodeOptions"),
    "SpladeEncodingMetadata": ("codeintel_rev.io.splade_manager", "SpladeEncodingMetadata"),
    "SpladeEncodingSummary": ("codeintel_rev.io.splade_manager", "SpladeEncodingSummary"),
    "SpladeExportOptions": ("codeintel_rev.io.splade_manager", "SpladeExportOptions"),
    "SpladeExportSummary": ("codeintel_rev.io.splade_manager", "SpladeExportSummary"),
    "SpladeIndexManager": ("codeintel_rev.io.splade_manager", "SpladeIndexManager"),
    "SpladeIndexMetadata": ("codeintel_rev.io.splade_manager", "SpladeIndexMetadata"),
}


def __getattr__(name: str) -> object:  # pragma: no cover - simple dispatch
    """Resolve exports lazily to avoid importing heavy adapter modules at import time.

    Parameters
    ----------
    name : str
        Export requested by the caller.

    Returns
    -------
    object
        Attribute resolved from the target adapter module.

    Raises
    ------
    AttributeError
        If the requested export is unknown.
    """
    try:
        module_path, attr_name = _EXPORTS[name]
    except KeyError as exc:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from exc
    module = import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:  # pragma: no cover - tooling convenience
    return sorted(set(globals()) | set(__all__))
