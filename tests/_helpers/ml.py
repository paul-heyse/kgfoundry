"""Machine learning-oriented test doubles (embeddings, text search sessions)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from codeintel_rev.runtime.request_context import session_id_var


@dataclass(slots=True)
class FakeEmbeddingClient:
    """Deterministic embedding client with in-memory vectors."""

    embedding_dim: int
    batch_size: int = 32
    vector_value: float = 1.0
    calls: list[list[str]] = field(default_factory=list)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return deterministic embeddings and record the batch."""
        entries = list(texts)
        self.calls.append(entries)
        return np.full(
            (len(entries), self.embedding_dim),
            self.vector_value,
            dtype=np.float32,
        )

    async def embed_batch_async(self, texts: Sequence[str]) -> np.ndarray:
        """Async variant mirroring embed_batch."""
        return self.embed_batch(texts)

    def embed_chunks(self, texts: Sequence[str], batch_size: int | None = None) -> np.ndarray:
        """Batch-aware embedding routine mirroring VLLMClient behavior."""
        if not texts:
            return np.empty((0, self.embedding_dim), dtype=np.float32)
        bs = batch_size or self.batch_size
        batches = [
            self.embed_batch(texts[index : index + bs]) for index in range(0, len(texts), bs)
        ]
        return np.vstack(batches)


@dataclass(slots=True)
class FakeTextSearchSession:
    """Utility for setting session IDs and per-session scopes in tests."""

    session_id: str = "session-test"

    @contextmanager
    def activate(self) -> Iterator[str]:
        """Set the request context session ID for the duration of a block."""
        token = session_id_var.set(self.session_id)
        try:
            yield self.session_id
        finally:
            session_id_var.reset(token)

    async def set_scope(self, scope_store: object, scope: dict | None) -> None:
        """Seed or clear the scope for this session."""
        setter = getattr(scope_store, "set", None)
        deleter = getattr(scope_store, "delete", None)
        if scope is None:
            if deleter is not None:
                await deleter(self.session_id)
            return
        if setter is None:
            raise AttributeError("scope_store must expose an async set method")
        await setter(self.session_id, scope)
