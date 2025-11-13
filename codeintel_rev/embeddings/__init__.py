"""Embedding provider public API."""

from __future__ import annotations

from codeintel_rev.embeddings.embedding_service import (
    EmbeddingMetadata,
    EmbeddingProvider,
    EmbeddingProviderBase,
    EmbeddingRuntimeError,
    HFEmbeddingProvider,
    VLLMProvider,
    get_embedding_provider,
)

__all__ = [
    "EmbeddingMetadata",
    "EmbeddingProvider",
    "EmbeddingProviderBase",
    "EmbeddingRuntimeError",
    "HFEmbeddingProvider",
    "VLLMProvider",
    "get_embedding_provider",
]
