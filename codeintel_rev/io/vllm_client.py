"""vLLM embedding client using msgspec for fast serialization.

OpenAI-compatible /v1/embeddings endpoint with batching support.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import msgspec
import numpy as np

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codeintel_rev.config.settings import VLLMConfig

LOGGER = get_logger(__name__)


class EmbeddingRequest(msgspec.Struct):
    """OpenAI-compatible embedding request payload.

    Request structure for the vLLM /v1/embeddings endpoint, matching the OpenAI
    API format. This allows vLLM to be used as a drop-in replacement for OpenAI's
    embedding API.

    The request can embed a single text (str) or a batch of texts (list[str]).
    Batch requests are more efficient as they're processed in parallel by the
    model.

    Attributes
    ----------
    input : str | list[str]
        Text(s) to embed. Can be a single string for one embedding, or a list
        of strings for batch embedding. Batch processing is more efficient.
        Each text should be a code chunk or query string.
    model : str
        Model identifier string. Must match a model loaded by the vLLM server.
        Defaults to "nomic-ai/nomic-embed-code" which is a code-specific
        embedding model with 2560 dimensions. The embedding dimensionality is
        surfaced via :class:`codeintel_rev.config.settings.VLLMConfig` ``embedding_dim``.
    """

    input: str | list[str]
    model: str


class EmbeddingData(msgspec.Struct):
    """Single embedding result from a batch request.

    Represents one embedding vector from a batch embedding request. Each text
    in the input batch produces one EmbeddingData object. The index field
    indicates the position in the original batch, which is important because
    vLLM may return results in a different order than the input.

    Attributes
    ----------
    embedding : list[float]
        Embedding vector as a list of floats. The length matches the model's
        dimension (e.g., 2560 for nomic-embed-code). Values are typically
        normalized for cosine similarity. The expected size is available as
        ``VLLMConfig.embedding_dim``.
    index : int
        Zero-based index indicating the position of this embedding in the
        original input batch. Used to match embeddings back to their input
        texts when results may be reordered.
    """

    embedding: list[float]
    index: int


class EmbeddingResponse(msgspec.Struct):
    """OpenAI-compatible embedding response payload.

    Response structure from the vLLM /v1/embeddings endpoint, matching the OpenAI
    API format. Contains the embedding vectors along with metadata about the
    request and model usage.

    The data field contains one EmbeddingData per input text. Results may be
    returned in a different order than the input, so use the index field to
    match embeddings to their original texts.

    Attributes
    ----------
    data : list[EmbeddingData]
        List of embedding results, one per input text. The list length matches
        the number of texts in the request. Each EmbeddingData contains the
        vector and its index in the original batch.
    model : str
        Model identifier that was used to generate the embeddings. Should match
        the model field from the request. Useful for verification and logging.
    usage : dict
        Token usage statistics dictionary. Typically contains keys like "prompt_tokens"
        and "total_tokens" indicating how many tokens were processed. Useful for
        monitoring and cost tracking.
    """

    data: list[EmbeddingData]
    model: str
    usage: dict


class VLLMClient:
    """vLLM embedding client with persistent HTTP connection pooling.

    Maintains a persistent HTTP client for connection reuse across embedding
    batches. This reduces latency by eliminating TCP handshake overhead and
    enables HTTP/1.1 keep-alive for better performance.

    The client is created during initialization and reused for all embed_batch
    calls. Connection pooling is configured with limits to prevent server
    overload. The client must be closed during application shutdown via the
    close() method to avoid resource leaks.

    Parameters
    ----------
    config : VLLMConfig
        vLLM configuration including base URL, timeout, and model name.

    Examples
    --------
    Create client and embed batch:

    >>> from codeintel_rev.config.settings import VLLMConfig
    >>> config = VLLMConfig(base_url="http://localhost:8000", model="test-model")
    >>> client = VLLMClient(config)
    >>> vectors = client.embed_batch(["def hello(): pass", "def world(): pass"])
    >>> vectors.shape
    (2, 2560)

    Cleanup during shutdown:

    >>> client.close()  # Must be called to close HTTP connections

    Notes
    -----
    Connection pool limits:
    - max_connections=100: Maximum total connections in pool
    - max_keepalive_connections=20: Maximum connections kept alive for reuse

    These limits prevent overwhelming the vLLM server while allowing efficient
    connection reuse for high-throughput embedding workloads.

    Internal attributes (not part of public API):
    - ``config``: vLLM configuration
    - ``_client``: Persistent HTTP client with connection pooling. Created during
      initialization and reused across all requests
    - ``_async_client``: Optional async HTTP client for concurrent embedding generation.
      Lazy-initialized on first call to embed_batch_async
    - ``_encoder``: Fast JSON encoder for request serialization
    - ``_decoder``: Fast JSON decoder for response deserialization
    """

    def __init__(self, config: VLLMConfig) -> None:
        self.config = config
        self._encoder = msgspec.json.Encoder()
        self._decoder = msgspec.json.Decoder(EmbeddingResponse)

        # Create persistent HTTP client with connection pooling
        self._client = httpx.Client(
            timeout=config.timeout_s,
            limits=httpx.Limits(
                max_connections=100,  # Maximum total connections in pool
                max_keepalive_connections=20,  # Maximum keep-alive connections
            ),
        )
        self._async_client: httpx.AsyncClient | None = None

        LOGGER.debug(
            "Initialized VLLMClient with persistent HTTP connection pool",
            extra={
                "base_url": config.base_url,
                "model": config.model,
                "timeout_s": config.timeout_s,
                "max_connections": 100,
                "max_keepalive_connections": 20,
            },
        )

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of texts using the vLLM service.

        Sends a batch of texts to the vLLM embedding service and returns their
        embedding vectors as a NumPy array. The function uses msgspec for fast
        JSON encoding/decoding, which is significantly faster than standard
        json module.

        The function handles reordering - vLLM may return embeddings in a
        different order than the input, so results are sorted by index to
        match the input sequence.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of texts to embed. Can be any sequence type (list, tuple, etc.).
            Empty sequence returns empty array. Each text should be a code chunk
            or query string suitable for the embedding model.

        Returns
        -------
        np.ndarray
            Embedding vectors as a 2D NumPy array of shape (len(texts), vec_dim)
            where vec_dim is the model's embedding dimension (e.g., 2560).
            Dtype is float32 for memory efficiency. Returns empty array (shape
            (0, ``self.config.embedding_dim``)) if texts is empty. The order
            matches the input texts.

        Notes
        -----
        The function uses the persistent HTTP client (self._client) created during
        initialization. This enables connection reuse and HTTP/1.1 keep-alive,
        reducing latency by eliminating TCP handshake overhead.

        If the request fails (network error, timeout, HTTP error), httpx will raise
        an exception (HTTPStatusError, TimeoutException, etc.). These exceptions
        propagate to the caller - handle them appropriately.

        The function does not retry failed requests. For production use, consider
        adding retry logic with exponential backoff for transient failures.
        """
        if not texts:
            return np.empty((0, self.config.embedding_dim), dtype=np.float32)

        request = EmbeddingRequest(input=list(texts), model=self.config.model)
        payload = self._encoder.encode(request)

        LOGGER.debug(
            "Embedding batch",
            extra={"batch_size": len(texts), "model": self.config.model},
        )

        # Use persistent client (no context manager - client is reused)
        response = self._client.post(
            f"{self.config.base_url}/embeddings",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = self._decoder.decode(response.content)

        # Sort by index and extract vectors
        sorted_data = sorted(result.data, key=lambda d: d.index)
        vectors = np.array([d.embedding for d in sorted_data], dtype=np.float32)

        LOGGER.debug(
            "Batch embedding completed",
            extra={
                "batch_size": len(texts),
                "vectors_shape": vectors.shape,
                "model": self.config.model,
            },
        )

        return vectors

    def embed_single(self, text: str) -> np.ndarray:
        """Embed a single string and return its vector.

        Parameters
        ----------
        text : str
            Text to embed.

        Returns
        -------
        np.ndarray
            One-dimensional embedding vector for the supplied text.

        Raises
        ------
        RuntimeError
            If the embedding service returns an empty response.
        """
        vectors = self.embed_batch([text])
        if vectors.size == 0:
            msg = "vLLM returned no vectors for single embed request"
            raise RuntimeError(msg)
        return vectors[0]

    def embed_chunks(
        self,
        texts: Sequence[str],
        batch_size: int | None = None,
    ) -> np.ndarray:
        """Embed texts in batches.

        This method processes multiple texts efficiently by splitting them into
        batches and sending each batch to the vLLM embedding service. Batching
        improves throughput by amortizing HTTP request overhead and allowing
        the service to process multiple texts in parallel.

        The method handles empty input gracefully, returning an empty array with
        the correct shape. Batch size can be customized per call or defaults to
        the client's configured batch size. Results are concatenated into a single
        array maintaining the input order.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of texts to embed. Can be any sequence type (list, tuple, etc.).
            Each text should be a code chunk or query string suitable for the
            embedding model. Empty sequence returns empty array.
        batch_size : int | None, optional
            Number of texts to process per batch. If None, uses the client's
            configured batch_size from config. Larger batches improve throughput
            but increase memory usage. Defaults to None (use config.batch_size).

        Returns
        -------
        np.ndarray
            Embeddings array of shape (len(texts), vec_dim) where vec_dim is the
            model's embedding dimension (e.g., 2560). Dtype is float32 for memory
            efficiency. Returns an empty array of shape (0, self.config.embedding_dim)
            when texts is empty. The order matches the input texts.
        """
        if not texts:
            return np.empty((0, self.config.embedding_dim), dtype=np.float32)

        bs = batch_size or self.config.batch_size
        all_vectors = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            vectors = self.embed_batch(batch)
            all_vectors.append(vectors)

        return np.vstack(all_vectors)

    async def embed_batch_async(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of texts asynchronously using the vLLM service.

        Async variant of embed_batch() that uses an async HTTP client for
        concurrent embedding generation. This is useful when embedding multiple
        queries concurrently during semantic search, as it allows multiple
        requests to proceed in parallel without blocking the event loop.

        The async client is lazy-initialized on first call and reused for all
        subsequent async embedding requests. Connection pooling is configured
        identically to the sync client.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of texts to embed. Can be any sequence type (list, tuple, etc.).
            Empty sequence returns empty array. Each text should be a code chunk
            or query string suitable for the embedding model.

        Returns
        -------
        np.ndarray
            Embedding vectors as a 2D NumPy array of shape (len(texts), vec_dim)
            where vec_dim is the model's embedding dimension (e.g., 2560).
            Dtype is float32 for memory efficiency. Returns empty array (shape
            (0, ``self.config.embedding_dim``)) if texts is empty. The order
            matches the input texts.

        Examples
        --------
        Embed batch asynchronously:

        >>> client = VLLMClient(config)
        >>> vectors = await client.embed_batch_async(["def hello(): pass"])
        >>> vectors.shape
        (1, 2560)

        Concurrent embedding:

        >>> import asyncio
        >>> tasks = [
        ...     client.embed_batch_async(["query 1"]),
        ...     client.embed_batch_async(["query 2"]),
        ...     client.embed_batch_async(["query 3"]),
        ... ]
        >>> results = await asyncio.gather(*tasks)

        Notes
        -----
        The async client is created lazily on first call to this method. This
        avoids creating an async client if only sync methods are used.

        Connection pooling is configured identically to the sync client:
        - max_connections=100
        - max_keepalive_connections=20

        If the request fails (network error, timeout, HTTP error), httpx will
        raise an exception (HTTPStatusError, TimeoutException, etc.). These
        exceptions propagate to the caller - handle them appropriately.
        """
        if not texts:
            return np.empty((0, self.config.embedding_dim), dtype=np.float32)

        # Lazy-initialize async client on first call
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=self.config.timeout_s,
                limits=httpx.Limits(
                    max_connections=100,  # Maximum total connections in pool
                    max_keepalive_connections=20,  # Maximum keep-alive connections
                ),
            )
            LOGGER.debug(
                "Initialized async HTTP client for VLLMClient",
                extra={
                    "base_url": self.config.base_url,
                    "model": self.config.model,
                },
            )

        request = EmbeddingRequest(input=list(texts), model=self.config.model)
        payload = self._encoder.encode(request)

        LOGGER.debug(
            "Embedding batch (async)",
            extra={"batch_size": len(texts), "model": self.config.model},
        )

        # Use async client with connection pooling
        response = await self._async_client.post(
            f"{self.config.base_url}/embeddings",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = self._decoder.decode(response.content)

        # Sort by index and extract vectors
        sorted_data = sorted(result.data, key=lambda d: d.index)
        vectors = np.array([d.embedding for d in sorted_data], dtype=np.float32)

        LOGGER.debug(
            "Batch embedding completed (async)",
            extra={
                "batch_size": len(texts),
                "vectors_shape": vectors.shape,
                "model": self.config.model,
            },
        )

        return vectors

    def close(self) -> None:
        """Close HTTP clients and release resources.

        Closes the persistent HTTP client and async client (if initialized),
        releasing all network connections and resources. This method must be
        called during application shutdown to avoid resource leaks.

        The method is idempotent - calling it multiple times is safe. After
        calling close(), the client should not be used for further requests.

        Typically called in FastAPI lifespan shutdown handler or application
        cleanup code.

        Examples
        --------
        Cleanup during shutdown:

        >>> client = VLLMClient(config)
        >>> # ... use client ...
        >>> client.close()  # Release resources

        Notes
        -----
        This method closes both the synchronous and asynchronous HTTP clients.
        If the async client was never initialized (never called embed_batch_async),
        only the sync client is closed.

        After calling close(), attempting to use embed_batch() or
        embed_batch_async() will raise httpx errors.
        """
        LOGGER.debug("Closing VLLMClient HTTP connections")
        self._client.close()
        if self._async_client is not None:
            # Close async client synchronously (for use in sync cleanup)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If event loop is running, schedule close
                    # Note: Task will complete asynchronously, but we can't await here
                    # Store reference to task to prevent garbage collection
                    close_task = loop.create_task(self._async_client.aclose())
                    # Task is scheduled but not awaited - will complete asynchronously
                    _ = close_task
                else:
                    loop.run_until_complete(self._async_client.aclose())
            except RuntimeError:
                # No event loop - create new one for cleanup
                asyncio.run(self._async_client.aclose())
            self._async_client = None
        LOGGER.debug("VLLMClient HTTP connections closed")

    async def aclose(self) -> None:
        """Async close for async context managers.

        Closes HTTP clients asynchronously. Use this method when cleaning up
        in async code (e.g., async context managers, async lifespan handlers).

        This method is idempotent - calling it multiple times is safe.

        Examples
        --------
        Async cleanup:

        >>> async with VLLMClient(config) as client:
        ...     vectors = await client.embed_batch_async(texts)
        ... # Client automatically closed

        Or manual async cleanup:

        >>> client = VLLMClient(config)
        >>> # ... use client ...
        >>> await client.aclose()  # Async cleanup

        Notes
        -----
        This method closes both clients asynchronously. Prefer this over
        close() when called from async code to avoid blocking the event loop.
        """
        LOGGER.debug("Closing VLLMClient HTTP connections (async)")
        self._client.close()
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        LOGGER.debug("VLLMClient HTTP connections closed (async)")


__all__ = [
    "EmbeddingData",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "VLLMClient",
]
