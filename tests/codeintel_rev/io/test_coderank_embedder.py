"""Tests for the CodeRank embedder helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pytest
from codeintel_rev.io.coderank_embedder import (
    CodeRankEmbedder,
    CodeRankEmbedderContext,
    SupportsCodeRankSettings,
)

from tests._helpers import assertions


class _FakeModel:
    """Fake model for testing CodeRank embedder."""

    def __init__(self) -> None:
        """Initialize fake model with empty inputs list."""
        self.last_inputs: list[str] = []

    def encode(
        self,
        texts: Iterable[str],
        *,
        normalize_embeddings: bool,
        batch_size: int,
    ) -> Sequence[Sequence[float]]:
        """Encode texts to embeddings and store inputs.

        Parameters
        ----------
        texts : Iterable[str]
            Text strings to encode.
        normalize_embeddings : bool
            Whether to normalize embeddings (unused).
        batch_size : int
            Batch size (unused).

        Returns
        -------
        Sequence[Sequence[float]]
            Stub embeddings [[0.1, 0.2]] for each input text.
        """
        _ = normalize_embeddings, batch_size
        self.last_inputs = list(texts)
        return [[0.1, 0.2] for _ in texts]


def _build_context(fake_model: _FakeModel) -> CodeRankEmbedderContext:
    """Build CodeRank embedder context with fake model provider.

    Parameters
    ----------
    fake_model : _FakeModel
        Fake model instance to use.

    Returns
    -------
    CodeRankEmbedderContext
        Context with fake model provider.
    """

    def _provider(settings: SupportsCodeRankSettings) -> _FakeModel:
        """Return fake model ignoring settings.

        Parameters
        ----------
        settings : SupportsCodeRankSettings
            Settings (ignored).

        Returns
        -------
        _FakeModel
            Fake model instance.
        """
        _ = settings
        return fake_model

    return CodeRankEmbedderContext(model_provider=_provider)


def test_encode_queries_applies_instruction_prefix() -> None:
    """Query encoding prepends the configured prefix."""
    fake_model = _FakeModel()

    settings = _EmbedderSettings(
        model_id="stub_queries",
        device="cpu",
        trust_remote_code=True,
        query_prefix="Represent this query: ",
        normalize=True,
        batch_size=4,
    )
    embedder = CodeRankEmbedder(settings=settings, context=_build_context(fake_model))
    vectors = embedder.encode_queries(["search scope"])

    assertions.expect_true(fake_model.last_inputs[0].startswith("Represent this query: "))
    assertions.expect_equal(vectors.shape, (1, 2))
    assertions.expect_equal(vectors.dtype, np.dtype(np.float32))


def test_encode_codes_requires_input() -> None:
    """Code encoding requires at least one snippet."""
    fake_model = _FakeModel()
    settings = _EmbedderSettings(
        model_id="stub_codes",
        device="cpu",
        trust_remote_code=True,
        query_prefix="prefix: ",
        normalize=True,
        batch_size=4,
    )
    embedder = CodeRankEmbedder(settings=settings, context=_build_context(fake_model))

    with pytest.raises(ValueError, match="code snippet"):
        embedder.encode_codes([])


@dataclass(frozen=True)
class _EmbedderSettings:
    """Test settings for CodeRank embedder."""

    model_id: str
    device: str
    trust_remote_code: bool
    query_prefix: str
    normalize: bool
    batch_size: int
