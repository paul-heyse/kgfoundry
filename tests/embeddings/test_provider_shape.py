"""Unit tests for the embedding provider base helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

import sys
import types

sys.path.append(str((Path(__file__).resolve().parents[2] / "src")))


if "codeintel_rev.io.vllm_engine" not in sys.modules:  # pragma: no cover - test shim
    stub = types.ModuleType("codeintel_rev.io.vllm_engine")

    class _StubEmbedder:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def embed_batch_with_stats(self, texts: Sequence[str]) -> tuple[np.ndarray, int]:
            return np.zeros((len(texts), 1), dtype=np.float32), len(texts)

        def close(self) -> None:
            pass

    stub.InprocessVLLMEmbedder = _StubEmbedder  # type: ignore[attr-defined]
    sys.modules["codeintel_rev.io.vllm_engine"] = stub

from codeintel_rev.config.settings import EmbeddingsConfig, IndexConfig
from codeintel_rev.embeddings.embedding_service import EmbeddingRuntimeError, _ProviderBase


class _DummyProvider(_ProviderBase):
    """Deterministic provider returning simple ramp vectors."""

    def __init__(self, *, vec_dim: int = 4) -> None:
        cfg = EmbeddingsConfig(
            provider="hf",
            model_name="dummy",
            device="cpu",
            batch_size=4,
            micro_batch_size=2,
            normalize=True,
            max_pending_batches=0,
        )
        index = IndexConfig(vec_dim=vec_dim)
        super().__init__(provider_name="dummy", config=cfg, index=index, device_label="cpu")
        self.calls = 0

    def _run_inference(self, texts: Sequence[str]) -> tuple[np.ndarray, int]:
        self.calls += 1
        base = np.arange(len(texts) * 4, dtype=np.float32).reshape(len(texts), 4)
        return base + self.calls, len(texts) * 8

    def _close_impl(self) -> None:
        """No-op for tests."""


def test_provider_normalizes_and_reports_dimension() -> None:
    provider = _DummyProvider()
    vectors = provider.embed_texts(["alpha", "beta"])
    provider.close()
    assert vectors.shape == (2, 4)
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, np.ones_like(norms), atol=1e-6)
    assert provider.metadata.dimension == 4
    assert provider.metadata.normalize is True


def test_provider_raises_on_dimension_mismatch() -> None:
    provider = _DummyProvider(vec_dim=8)
    with pytest.raises(EmbeddingRuntimeError):
        provider.embed_texts(["only"])
    provider.close()
