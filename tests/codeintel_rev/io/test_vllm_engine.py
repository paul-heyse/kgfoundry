from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from codeintel_rev.config.settings import VLLMConfig, VLLMRunMode


class _StubTokenizer:
    def __call__(self, texts: list[str], **_: Any) -> dict[str, list[list[int]]]:
        input_ids = [[len(texts)] for _ in texts]
        return {"input_ids": input_ids}


class _StubPooler:
    def __init__(self, **_: Any) -> None:  # pragma: no cover - configuration stub
        pass


class _StubLLM:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    def embed(self, prompts: list[dict[str, Any]]) -> list[SimpleNamespace]:
        self.calls.append(prompts)

        def _result(prompt: dict[str, Any]) -> SimpleNamespace:
            tokens = prompt.get("prompt_token_ids", []) or []
            return SimpleNamespace(outputs=SimpleNamespace(embedding=[float(len(tokens)), 0.0]))

        return [_result(prompt) for prompt in prompts]


@pytest.fixture(autouse=True)
def _patch_vllm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "codeintel_rev.io.vllm_engine.AutoTokenizer",
        SimpleNamespace(from_pretrained=lambda *_: _StubTokenizer()),
    )

    def _llm_factory(*_: object, **__: object) -> _StubLLM:
        return _StubLLM()

    monkeypatch.setattr("codeintel_rev.io.vllm_engine.LLM", _llm_factory)
    monkeypatch.setattr(
        "codeintel_rev.io.vllm_engine.PoolerConfig",
        _StubPooler,
    )


def test_embed_batch_returns_expected_shape() -> None:
    config = VLLMConfig(
        model="stub",
        embedding_dim=2,
        run=VLLMRunMode(mode="inprocess"),
    )
    from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder

    embedder = InprocessVLLMEmbedder(config)
    vectors = embedder.embed_batch(["alpha", "beta"])
    assert vectors.shape == (2, config.embedding_dim)
    assert vectors.dtype == np.float32


def test_embed_batch_handles_empty_input() -> None:
    config = VLLMConfig(
        model="stub",
        embedding_dim=3,
        run=VLLMRunMode(mode="inprocess"),
    )
    from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder

    embedder = InprocessVLLMEmbedder(config)
    vectors = embedder.embed_batch([])
    assert vectors.shape == (0, config.embedding_dim)
    assert np.allclose(vectors, 0.0)
