"""Tests for the VLLM embedding engine wrapper."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
from codeintel_rev.config.api import VLLMSettings
from codeintel_rev.io.vllm_engine import (
    LLM,
    InprocessVLLMContext,
    InprocessVLLMEmbedder,
    TokenizerProtocol,
    TokensPrompt,
)

from tests._helpers import assertions


class _StubTokenizer:
    def __call__(self, texts: list[str], **_: object) -> dict[str, list[list[int]]]:
        input_ids = [[len(text)] for text in texts]
        return {"input_ids": input_ids}


class _StubPooler:
    def __init__(self, **_: object) -> None:  # pragma: no cover - configuration stub
        pass


@dataclass(frozen=True)
class _StubTokensPrompt:
    prompt_token_ids: list[int]


class _StubLLM:
    def __init__(self, *_: object, **__: object) -> None:
        self.calls: list[list[list[int]]] = []

    def embed(self, prompts: Sequence[TokensPrompt]) -> list[_StubEmbeddingResult]:
        token_ids = [prompt.prompt_token_ids for prompt in prompts]
        self.calls.append([list(ids) for ids in token_ids])

        def _result(value: list[int]) -> _StubEmbeddingResult:
            embedding = _StubEmbeddingOutput(embedding=[float(len(value)), 0.0])
            return _StubEmbeddingResult(outputs=embedding)

        return [_result(ids) for ids in token_ids]

    def shutdown(self) -> None:
        """Protocol shim for graceful shutdown."""


@dataclass(frozen=True)
class _StubEmbeddingOutput:
    embedding: list[float]


@dataclass(frozen=True)
class _StubEmbeddingResult:
    outputs: _StubEmbeddingOutput


def _build_context() -> InprocessVLLMContext:
    def _tokenizer_factory(_model_id: str) -> TokenizerProtocol:
        return cast("TokenizerProtocol", _StubTokenizer())

    def _llm_factory(_config: VLLMSettings) -> LLM:
        return cast("LLM", _StubLLM())

    def _tokens_prompt_factory(token_ids: Sequence[int]) -> TokensPrompt:
        return cast("TokensPrompt", _StubTokensPrompt(prompt_token_ids=list(token_ids)))

    return InprocessVLLMContext(
        tokenizer_factory=_tokenizer_factory,
        llm_factory=_llm_factory,
        tokens_prompt_factory=_tokens_prompt_factory,
    )


def test_embed_batch_returns_expected_shape() -> None:
    """Batch embedding produces the configured dimensionality."""
    config = VLLMSettings(
        model="nomic-ai/nomic-embed-code",
        embedding_dim=2,
        run_mode="inprocess",
    )

    embedder = InprocessVLLMEmbedder(config, context=_build_context())
    vectors = embedder.embed_batch(["alpha", "beta"])
    assertions.expect_equal(vectors.shape, (2, config.embedding_dim))
    assertions.expect_equal(vectors.dtype, np.dtype(np.float32))


def test_embed_batch_handles_empty_input() -> None:
    """Empty inputs produce zero-row embeddings."""
    config = VLLMSettings(
        model="nomic-ai/nomic-embed-code",
        embedding_dim=3,
        run_mode="inprocess",
    )

    embedder = InprocessVLLMEmbedder(config, context=_build_context())
    vectors = embedder.embed_batch([])
    assertions.expect_equal(vectors.shape, (0, config.embedding_dim))
    assertions.expect_true(np.allclose(vectors, 0.0))
