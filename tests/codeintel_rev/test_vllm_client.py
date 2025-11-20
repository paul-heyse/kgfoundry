"""Tests for vLLM client embedding operations and transport modes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import numpy as np
import pytest
from codeintel_rev.config.api import VLLMSettings
from codeintel_rev.io.vllm_client import VLLMClient, VLLMTransportContext

if TYPE_CHECKING:
    import httpx
    from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
else:  # pragma: no cover - type-only dependency
    import httpx

from tests._helpers import assertions, ml


class _FailingHTTPClient:
    """Failing HTTP client for testing error handling."""

    def __init__(self) -> None:
        """Initialize failing client with counters."""
        self.closed = False
        self.post_calls = 0

    def post(self, *_: object, **__: object) -> object:
        """Raise AssertionError to prevent HTTP client usage.

        Parameters
        ----------
        *_ : object
            Positional arguments (unused).
        **__ : object
            Keyword arguments (unused).

        Raises
        ------
        AssertionError
            Always raised with message "HTTP client should not be used".
        """
        self.post_calls += 1
        message = "HTTP client should not be used"
        raise AssertionError(message)

    def close(self) -> None:
        """Mark client as closed."""
        self.closed = True


class _FailingAsyncClient:
    """Failing async HTTP client for testing error handling."""

    def __init__(self) -> None:
        """Initialize failing async client with counters."""
        self.closed = False
        self.post_calls = 0

    async def post(self, *_: object, **__: object) -> object:
        """Raise AssertionError to prevent async HTTP client usage.

        Parameters
        ----------
        *_ : object
            Positional arguments (unused).
        **__ : object
            Keyword arguments (unused).

        Raises
        ------
        AssertionError
            Always raised with message "Async HTTP client should not be used".
        """
        self.post_calls += 1
        message = "Async HTTP client should not be used"
        raise AssertionError(message)

    async def aclose(self) -> None:
        """Mark async client as closed."""
        self.closed = True


class _StubInprocessEngine:
    """Stub inprocess engine for testing VLLM client."""

    def __init__(self, embedding_dim: int) -> None:
        """Initialize stub engine with embedding dimension.

        Parameters
        ----------
        embedding_dim : int
            Embedding dimension.
        """
        self.embedding_dim = embedding_dim
        self.embed_batch = MagicMock(return_value=np.ones((1, embedding_dim), dtype=np.float32))
        self.closed = False

    def close(self) -> None:
        """Mark inprocess engine as closed."""
        self.closed = True


def _build_transport_context(
    *,
    http_client: httpx.Client | None = None,
    async_client: httpx.AsyncClient | None = None,
    inprocess_engine_factory: Callable[[VLLMSettings], _StubInprocessEngine] | None = None,
) -> VLLMTransportContext:
    """Build transport context with stub factories.

    Parameters
    ----------
    http_client : httpx.Client | None, optional
        HTTP client to use (creates failing client if None). Defaults to None.
    async_client : httpx.AsyncClient | None, optional
        Async client to use (creates failing client if None). Defaults to None.
    inprocess_engine_factory : Callable[[VLLMSettings], _StubInprocessEngine] | None, optional
        Inprocess engine factory (raises if None). Defaults to None.

    Returns
    -------
    VLLMTransportContext
        Context with stub factories.
    """
    http_instance = cast("httpx.Client", http_client or _FailingHTTPClient())
    async_instance = cast("httpx.AsyncClient", async_client or _FailingAsyncClient())

    def _http_factory(_: VLLMSettings) -> httpx.Client:
        """Return HTTP client instance ignoring settings.

        Returns
        -------
        httpx.Client
            HTTP client instance.
        """
        return http_instance

    def _async_factory(_: VLLMSettings) -> httpx.AsyncClient:
        """Return async client instance ignoring settings.

        Returns
        -------
        httpx.AsyncClient
            Async client instance.
        """
        return async_instance

    def _inprocess_factory(config: VLLMSettings) -> _StubInprocessEngine:
        """Create inprocess engine from config or raise.

        Parameters
        ----------
        config : VLLMSettings
            VLLM settings.

        Returns
        -------
        _StubInprocessEngine
            Stub inprocess engine instance.

        Raises
        ------
        AssertionError
            If inprocess_engine_factory is None.
        """
        if inprocess_engine_factory is not None:
            return inprocess_engine_factory(config)
        message = "Inprocess engine should not be used in this test"
        raise AssertionError(message)

    return VLLMTransportContext(
        http_client_factory=_http_factory,
        async_client_factory=_async_factory,
        inprocess_embedder_factory=cast(
            "Callable[[VLLMSettings], InprocessVLLMEmbedder]",
            _inprocess_factory,
        ),
    )


def test_embed_batch_empty_uses_configured_dimension() -> None:
    """Empty batches should produce arrays with the configured embedding width."""
    config = VLLMSettings(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=384,
        run_mode="http",
    )
    transport_context = _build_transport_context()
    client = VLLMClient(config, transport_context=transport_context)
    try:
        result = client.embed_batch([])
    finally:
        client.close()
    assertions.expect_equal(result.shape, (0, config.embedding_dim))
    assertions.expect_equal(result.dtype, np.dtype(np.float32))


def test_embed_chunks_empty_uses_configured_dimension() -> None:
    """Chunk embedding should return empty arrays without remote calls."""
    config = VLLMSettings(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=128,
        run_mode="http",
    )
    transport_context = _build_transport_context()
    client = VLLMClient(config, transport_context=transport_context)
    try:
        result = client.embed_chunks([], batch_size=4)
        assertions.expect_equal(result.shape, (0, config.embedding_dim))
        assertions.expect_equal(result.dtype, np.dtype(np.float32))
    finally:
        client.close()


def test_embed_chunks_empty_does_not_invoke_embed_batch() -> None:
    """Fake embedding client ensures embed_batch is skipped for empty data."""
    client = ml.FakeEmbeddingClient(embedding_dim=192, batch_size=4)
    result = client.embed_chunks([], batch_size=4)
    assertions.expect_equal(result.shape, (0, 192))
    assertions.expect_sequence_equal(client.calls, [])


@pytest.mark.asyncio
async def test_embed_batch_async_empty_uses_configured_dimension() -> None:
    """Async embedding should return appropriately shaped arrays for empty input."""
    config = VLLMSettings(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=1024,
        run_mode="http",
    )
    async_client = _FailingAsyncClient()
    transport_context = _build_transport_context(
        async_client=cast("httpx.AsyncClient", async_client)
    )
    client = VLLMClient(config, transport_context=transport_context)
    try:
        result = await client.embed_batch_async([])
    finally:
        client.close()

    assertions.expect_equal(result.shape, (0, config.embedding_dim))
    assertions.expect_equal(result.dtype, np.dtype(np.float32))


def test_vllm_client_inprocess_uses_local_engine() -> None:
    """Local transport should delegate to the in-process embedder."""
    config = VLLMSettings(
        model="unit-test",
        embedding_dim=16,
        run_mode="inprocess",
    )
    stub_engine = _StubInprocessEngine(config.embedding_dim)

    def _engine_factory(_: VLLMSettings) -> _StubInprocessEngine:
        """Return stub engine ignoring settings.

        Returns
        -------
        _StubInprocessEngine
            Pre-configured stub engine.
        """
        return stub_engine

    transport_context = _build_transport_context(inprocess_engine_factory=_engine_factory)
    client = VLLMClient(config, transport_context=transport_context)
    try:
        result = client.embed_batch(["hello world"])
    finally:
        client.close()
    stub_engine.embed_batch.assert_called_once()
    np.testing.assert_allclose(result, np.ones((1, config.embedding_dim), dtype=np.float32))
