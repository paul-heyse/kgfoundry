from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest
from codeintel_rev.config.settings import VLLMConfig
from codeintel_rev.io.vllm_client import VLLMClient


def test_embed_batch_empty_uses_configured_dimension() -> None:
    """Empty batches should produce arrays with the configured embedding width."""
    config = VLLMConfig(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=384,
    )
    with patch("httpx.Client.post", new_callable=MagicMock) as mock_post:
        client = VLLMClient(config)
        try:
            result = client.embed_batch([])
        finally:
            client.close()
        assert result.shape == (0, config.embedding_dim)
        assert result.dtype == np.float32
        mock_post.assert_not_called()


def test_embed_chunks_empty_uses_configured_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunk embedding should bypass network calls when no data is supplied."""
    config = VLLMConfig(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=128,
    )
    client = VLLMClient(config)
    try:
        mock_embed_batch = MagicMock()
        monkeypatch.setattr(client, "embed_batch", mock_embed_batch)

        result = client.embed_chunks([], batch_size=4)

        assert result.shape == (0, config.embedding_dim)
        assert result.dtype == np.float32
        mock_embed_batch.assert_not_called()
    finally:
        client.close()


@pytest.mark.asyncio
async def test_embed_batch_async_empty_uses_configured_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async embedding should return appropriately shaped arrays for empty input."""
    config = VLLMConfig(
        base_url="http://127.0.0.1:9000/v1",
        model="unit-test",
        embedding_dim=1024,
    )
    async_client_mock = MagicMock()
    monkeypatch.setattr(httpx, "AsyncClient", async_client_mock)
    client = VLLMClient(config)
    try:
        result = await client.embed_batch_async([])
    finally:
        client.close()

    assert result.shape == (0, config.embedding_dim)
    assert result.dtype == np.float32
    async_client_mock.assert_not_called()
