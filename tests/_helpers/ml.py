"""Machine learning-oriented test doubles (embeddings, text search sessions)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

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
        """Return deterministic embeddings and record the batch.

        Parameters
        ----------
        texts : Sequence[str]
            Text strings to embed.

        Returns
        -------
        np.ndarray
            Array of shape (len(texts), embedding_dim) filled with vector_value.
        """
        entries = list(texts)
        self.calls.append(entries)
        return np.full(
            (len(entries), self.embedding_dim),
            self.vector_value,
            dtype=np.float32,
        )

    async def embed_batch_async(self, texts: Sequence[str]) -> np.ndarray:
        """Async variant mirroring embed_batch.

        Parameters
        ----------
        texts : Sequence[str]
            Text strings to embed.

        Returns
        -------
        np.ndarray
            Array of shape (len(texts), embedding_dim) filled with vector_value.
        """
        return self.embed_batch(texts)

    def embed_chunks(self, texts: Sequence[str], batch_size: int | None = None) -> np.ndarray:
        """Batch-aware embedding routine mirroring VLLMClient behavior.

        Parameters
        ----------
        texts : Sequence[str]
            Text strings to embed.
        batch_size : int | None, optional
            Batch size for processing (uses instance default if None).

        Returns
        -------
        np.ndarray
            Concatenated array of embeddings from all batches.
        """
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
        """Set the request context session ID for the duration of a block.

        Yields
        ------
        str
            Session ID string for use within the context block.
        """
        token = session_id_var.set(self.session_id)
        try:
            yield self.session_id
        finally:
            session_id_var.reset(token)

    async def set_scope(
        self,
        scope_store: object,
        scope: Mapping[str, object] | None,
    ) -> None:
        """Seed or clear the scope for this session.

        Parameters
        ----------
        scope_store : object
            Scope store instance with async set/delete methods.
        scope : Mapping[str, object] | None
            Scope dictionary to set, or None to clear.

        Raises
        ------
        AttributeError
            If scope_store does not expose an async set method when scope is provided.
        """
        setter = getattr(scope_store, "set", None)
        deleter = getattr(scope_store, "delete", None)
        if scope is None:
            if deleter is not None:
                await deleter(self.session_id)
            return
        if setter is None:
            message = "scope_store must expose an async set method"
            raise AttributeError(message)
        await setter(self.session_id, scope)
