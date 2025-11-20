"""Unit tests for the embedding provider base helpers."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from codeintel_rev.config.api import EmbeddingsSettings

from tests._helpers import assertions

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

if "codeintel_rev.io.vllm_engine" not in sys.modules:  # pragma: no cover - test shim
    stub = types.ModuleType("codeintel_rev.io.vllm_engine")

    class _StubEmbedder:
        """Stub embedder for testing provider shape."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            """Initialize stub embedder (no-op)."""
            return

        @staticmethod
        def embed_batch_with_stats(texts: Sequence[str]) -> tuple[np.ndarray, int]:
            """Stub embed_batch_with_stats method.

            Parameters
            ----------
            texts : Sequence[str]
                Texts to embed.

            Returns
            -------
            tuple[np.ndarray, int]
                Zero vectors and text count.
            """
            return np.zeros((len(texts), 1), dtype=np.float32), len(texts)

        @staticmethod
        def close() -> None:
            """Stub close method."""
            return

    cast("Any", stub).InprocessVLLMEmbedder = _StubEmbedder
    sys.modules["codeintel_rev.io.vllm_engine"] = stub

embedding_module = importlib.import_module("codeintel_rev.embeddings")
EmbeddingProviderBase = embedding_module.EmbeddingProviderBase
EmbeddingRuntimeError = embedding_module.EmbeddingRuntimeError


class _DummyProvider(EmbeddingProviderBase):
    """Deterministic provider returning simple ramp vectors."""

    def __init__(self, *, vec_dim: int = 4) -> None:
        cfg = EmbeddingsSettings(
            provider="hf",
            model_name="dummy",
            device="cpu",
            batch_size=4,
            micro_batch_size=2,
            normalize=True,
            max_pending_batches=0,
        )
        super().__init__(provider_name="dummy", config=cfg, vec_dim=vec_dim, device_label="cpu")
        self.calls = 0

    def _run_inference(self, texts: Sequence[str]) -> tuple[np.ndarray, int]:
        """Run inference and return ramp vectors.

        Parameters
        ----------
        texts : Sequence[str]
            Texts to embed.

        Returns
        -------
        tuple[np.ndarray, int]
            Tuple of ramp vectors and token count.
        """
        self.calls += 1
        base = np.arange(len(texts) * 4, dtype=np.float32).reshape(len(texts), 4)
        return base + self.calls, len(texts) * 8

    def _close_impl(self) -> None:
        """No-op for tests."""


def test_provider_normalizes_and_reports_dimension() -> None:
    """Verify provider normalizes vectors and reports correct dimension."""
    provider = _DummyProvider()
    vectors = provider.embed_texts(["alpha", "beta"])
    provider.close()
    assertions.expect_equal(vectors.shape, (2, 4))
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, np.ones_like(norms), atol=1e-6)
    assertions.expect_equal(provider.metadata.dimension, 4)
    assertions.expect_true(provider.metadata.normalize is True, reason="normalize should be True")


def test_provider_raises_on_dimension_mismatch() -> None:
    """Verify provider raises error when vector dimension doesn't match config."""
    provider = _DummyProvider(vec_dim=8)
    with pytest.raises(EmbeddingRuntimeError):
        provider.embed_texts(["only"])
    provider.close()
