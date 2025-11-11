"""vLLM embedding client using msgspec for fast serialization.

OpenAI-compatible /v1/embeddings endpoint with batching support.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, cast

import msgspec

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32, gate_import
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx
    import numpy as np

    from codeintel_rev.config.settings import VLLMConfig
    from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
else:
    httpx = cast("httpx", LazyModule("httpx", "vLLM HTTP client"))

LOGGER = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_numpy() -> ModuleType:
    """Load numpy lazily when embeddings are computed.

    Extended Summary
    ----------------
    This function provides lazy import of the NumPy module for embedding operations
    in VLLMClient. It uses LRU caching to ensure the module is imported only once
    per process, reducing import overhead. The function gates the import using
    ``gate_import`` to prevent eager loading of NumPy when it's not needed, which
    is important for keeping the codebase lightweight and avoiding unnecessary
    dependencies in environments where NumPy may not be available.

    Returns
    -------
    ModuleType
        The lazily imported NumPy module. The return type is ``ModuleType`` to
        match the runtime type, but the actual value is the ``numpy`` module
        (cast from the gate_import result).

    Notes
    -----
    Time complexity O(1) after first call (cached); O(n) on first call where n
    is import overhead. Space complexity O(1) - single module reference cached.
    The function performs module import I/O on first call only. Thread-safe due
    to lru_cache implementation. Uses ``gate_import`` to ensure proper typing
    facade compliance and prevent eager NumPy loading.
    """
    return cast(
        "np",
        gate_import(
            "numpy",
            "Embedding batching operations in VLLMClient",
        ),
    )


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
    """vLLM embedding client supporting HTTP or in-process execution.

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
        self._mode = getattr(config.run, "mode", "inprocess")
        self._client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._local_engine: InprocessVLLMEmbedder | None = None
        self._local_semaphore: asyncio.Semaphore | None = None

        if self._mode == "inprocess":
            self._initialize_local_engine()
        else:
            self._initialize_http_client()

    def _initialize_local_engine(self) -> None:
        engine_module = import_module("codeintel_rev.io.vllm_engine")
        engine_cls = engine_module.InprocessVLLMEmbedder
        self._local_engine = engine_cls(self.config)
        LOGGER.debug(
            "Initialized VLLMClient in in-process mode",
            extra={"model": self.config.model},
        )

    def _initialize_http_client(self) -> None:
        self._client = httpx.Client(
            timeout=self.config.timeout_s,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )
        LOGGER.debug(
            "Initialized VLLMClient HTTP transport",
            extra={
                "base_url": self.config.base_url,
                "model": self.config.model,
                "timeout_s": self.config.timeout_s,
                "max_connections": 100,
                "max_keepalive_connections": 20,
            },
        )

    def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
        """Embed texts using the configured transport (HTTP or local).

        Extended Summary
        ----------------
        This method generates dense vector embeddings for a batch of text strings using
        the configured vLLM service. It supports both HTTP-based remote embedding (when
        vLLM runs as a separate service) and in-process embedding (when vLLM is loaded
        locally). The method automatically selects the appropriate transport based on
        the client configuration and handles empty input batches gracefully. This is the
        primary entry point for generating embeddings in Stage-0 retrieval pipelines.

        Parameters
        ----------
        texts : Sequence[str]
            Ordered sequence of text strings to embed. Empty sequences result in an
            empty embedding matrix. Each text will be tokenized and encoded by the
            vLLM model to produce a dense vector representation.

        Returns
        -------
        NDArrayF32
            Embedding matrix with shape (N, embedding_dim) where N is len(texts) and
            embedding_dim matches the configured model's output dimensionality. Dtype is
            float32. Each row corresponds to the embedding of the corresponding input text.

        Notes
        -----
        Time complexity O(N * T) where N is batch size and T is average token count per
        text, plus network latency for HTTP mode. Space complexity O(N * embedding_dim)
        for the result matrix. The method performs network I/O in HTTP mode or GPU
        computation in local mode. Thread-safe if the underlying HTTP client or local
        engine is thread-safe. Empty batches return shape (0, embedding_dim).
        """
        np_module = _get_numpy()
        if not texts:
            return np_module.empty(
                (0, self.config.embedding_dim),
                dtype=np_module.float32,
            )

        if self._local_engine is not None:
            vectors = self._local_engine.embed_batch(texts)
        else:
            vectors = self._embed_batch_http(texts)

        LOGGER.debug(
            "Batch embedding completed",
            extra={
                "batch_size": len(texts),
                "vectors_shape": vectors.shape,
                "model": self.config.model,
                "mode": self._mode,
            },
        )
        return vectors

    def _embed_batch_http(self, texts: Sequence[str]) -> NDArrayF32:
        request = EmbeddingRequest(input=list(texts), model=self.config.model)
        payload = self._encoder.encode(request)

        LOGGER.debug(
            "Embedding batch",
            extra={"batch_size": len(texts), "model": self.config.model},
        )

        client = self._require_http_client()
        response = client.post(
            f"{self.config.base_url}/embeddings",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = self._decoder.decode(response.content)

        # Sort by index and extract vectors
        sorted_data = sorted(result.data, key=lambda d: d.index)
        np_module = _get_numpy()
        return np_module.array(
            [d.embedding for d in sorted_data],
            dtype=np_module.float32,
        )

    def embed_single(self, text: str) -> NDArrayF32:
        """Embed a single string and return its vector.

        Parameters
        ----------
        text : str
            Text to embed.

        Returns
        -------
        NDArrayF32
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
    ) -> NDArrayF32:
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
        NDArrayF32
            Embeddings array of shape (len(texts), vec_dim) where vec_dim is the
            model's embedding dimension (e.g., 2560). Dtype is float32 for memory
            efficiency. Returns an empty array of shape (0, self.config.embedding_dim)
            when texts is empty. The order matches the input texts.
        """
        np_module = _get_numpy()
        if not texts:
            return np_module.empty(
                (0, self.config.embedding_dim),
                dtype=np_module.float32,
            )

        bs = batch_size or self.config.batch_size
        all_vectors = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            vectors = self.embed_batch(batch)
            all_vectors.append(vectors)

        return np_module.vstack(all_vectors)

    async def embed_batch_async(self, texts: Sequence[str]) -> NDArrayF32:
        """Asynchronous variant of embed_batch for async/await workflows.

        Extended Summary
        ----------------
        This method provides an asynchronous interface for generating dense vector
        embeddings, enabling non-blocking embedding generation in async contexts.
        It supports both HTTP-based remote embedding (via async HTTP client) and
        in-process embedding (via async local engine wrapper). The method handles
        empty input batches gracefully and provides the same functionality as
        embed_batch but with async/await semantics for use in async event loops.

        Parameters
        ----------
        texts : Sequence[str]
            Ordered sequence of text strings to embed. Empty sequences result in an
            empty embedding matrix. Each text will be tokenized and encoded by the
            vLLM model to produce a dense vector representation.

        Returns
        -------
        NDArrayF32
            Embedding matrix with shape (N, embedding_dim) where N is len(texts) and
            embedding_dim matches the configured model's output dimensionality. Dtype is
            float32. Each row corresponds to the embedding of the corresponding input text.

        Notes
        -----
        Time complexity O(N * T) where N is batch size and T is average token count per
        text, plus network latency for HTTP mode. Space complexity O(N * embedding_dim)
        for the result matrix. The method performs async network I/O in HTTP mode or
        async GPU computation in local mode. Thread-safe if the underlying async HTTP
        client or local engine is thread-safe. Empty batches return shape (0, embedding_dim).
        """
        np_module = _get_numpy()
        if not texts:
            return np_module.empty(
                (0, self.config.embedding_dim),
                dtype=np_module.float32,
            )

        if self._local_engine is not None:
            return await self._embed_batch_async_local(texts)

        async_client = self._ensure_async_http_client()
        request = EmbeddingRequest(input=list(texts), model=self.config.model)
        payload = self._encoder.encode(request)

        LOGGER.debug(
            "Embedding batch (async)",
            extra={"batch_size": len(texts), "model": self.config.model},
        )

        response = await async_client.post(
            f"{self.config.base_url}/embeddings",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = self._decoder.decode(response.content)

        # Sort by index and extract vectors
        sorted_data = sorted(result.data, key=lambda d: d.index)
        vectors = np_module.array(
            [d.embedding for d in sorted_data],
            dtype=np_module.float32,
        )

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
        """Close HTTP clients, async clients, and the local engine."""
        LOGGER.debug("Closing VLLMClient resources", extra={"mode": self._mode})
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._async_client is not None:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                close_task = loop.create_task(self._async_client.aclose())
                _ = close_task
            elif loop:
                loop.run_until_complete(self._async_client.aclose())
            else:
                asyncio.run(self._async_client.aclose())
            self._async_client = None
        if self._local_engine is not None:
            self._local_engine.close()
            self._local_engine = None
        LOGGER.debug("VLLMClient resources closed")

    async def aclose(self) -> None:
        """Asynchronously release all clients/engines."""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._local_engine is not None:
            self._local_engine.close()
            self._local_engine = None
        LOGGER.debug("VLLMClient resources closed (async)")

    async def _embed_batch_async_local(self, texts: Sequence[str]) -> NDArrayF32:
        if self._local_engine is None:
            msg = "Local vLLM engine not initialized."
            raise RuntimeError(msg)
        if self._local_semaphore is None:
            permits = max(1, self.config.max_concurrent_requests)
            self._local_semaphore = asyncio.Semaphore(permits)
        async with self._local_semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._local_engine.embed_batch, list(texts))

    def _ensure_async_http_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=self.config.timeout_s,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                ),
            )
            LOGGER.debug(
                "Initialized async HTTP client for VLLMClient",
                extra={
                    "base_url": self.config.base_url,
                    "model": self.config.model,
                },
            )
        return self._async_client

    def _require_http_client(self) -> httpx.Client:
        if self._client is None:
            msg = "HTTP transport not initialized; set VLLM run mode to 'http'."
            raise RuntimeError(msg)
        return self._client


__all__ = [
    "EmbeddingData",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "VLLMClient",
]
