"""Tests for vLLM client embedding operations and transport modes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from codeintel_rev.config.api import VLLMSettings
from codeintel_rev.io.vllm_client import VLLMClient, VLLMTransportContext

if TYPE_CHECKING:
    import httpx
    from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
else:  # pragma: no cover - type-only dependency
    import httpx

from tests._helpers import assertions


class _FailingHTTPClient:
    def __init__(self) -> None:
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
    def __init__(self) -> None:
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
    def __init__(self, embedding_dim: int) -> None:
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
    http_instance = cast("httpx.Client", http_client or _FailingHTTPClient())
    async_instance = cast("httpx.AsyncClient", async_client or _FailingAsyncClient())

    def _http_factory(_: VLLMSettings) -> httpx.Client:
        return http_instance

    def _async_factory(_: VLLMSettings) -> httpx.AsyncClient:
        return async_instance

    def _inprocess_factory(config: VLLMSettings) -> _StubInprocessEngine:
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
    """Chunk embedding should bypass network calls when no data is supplied."""
    config = VLLMSettings(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=128,
        run_mode="http",
    )
    transport_context = _build_transport_context()
    client = VLLMClient(config, transport_context=transport_context)
    try:
        mock_embed_batch = MagicMock()
        with patch.object(client, "embed_batch", mock_embed_batch):
            result = client.embed_chunks([], batch_size=4)

        assertions.expect_equal(result.shape, (0, config.embedding_dim))
        assertions.expect_equal(result.dtype, np.dtype(np.float32))
        mock_embed_batch.assert_not_called()
    finally:
        client.close()


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
        return stub_engine

    transport_context = _build_transport_context(inprocess_engine_factory=_engine_factory)
    client = VLLMClient(config, transport_context=transport_context)
    try:
        result = client.embed_batch(["hello world"])
    finally:
        client.close()
    stub_engine.embed_batch.assert_called_once()
    np.testing.assert_allclose(result, np.ones((1, config.embedding_dim), dtype=np.float32))
