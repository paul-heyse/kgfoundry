from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
from codeintel_rev.config.settings import VLLMConfig, VLLMRunMode


class _StubTokenizer:
    def __call__(self, texts: list[str], **_: Any) -> dict[str, list[list[int]]]:
        input_ids = [[len(text)] for text in texts]
        return {"input_ids": input_ids}


class _StubPooler:
    def __init__(self, **_: Any) -> None:  # pragma: no cover - configuration stub
        pass


@dataclass
class _StubTokensPrompt:
    prompt_token_ids: list[int]


class _StubLLM:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.calls: list[list[list[int]]] = []

    def embed(self, prompts: Sequence[_StubTokensPrompt]) -> list[SimpleNamespace]:
        token_ids = [prompt.prompt_token_ids for prompt in prompts]
        self.calls.append([list(ids) for ids in token_ids])

        def _result(value: list[int]) -> SimpleNamespace:
            return SimpleNamespace(outputs=SimpleNamespace(embedding=[float(len(value)), 0.0]))

        return [_result(ids) for ids in token_ids]


@pytest.fixture(autouse=True)
def _patch_vllm(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    fake_vllm = ModuleType("vllm")
    fake_config = ModuleType("vllm.config")
    fake_inputs = ModuleType("vllm.inputs")
    fake_vllm.__dict__["LLM"] = _StubLLM
    fake_config.__dict__["PoolerConfig"] = _StubPooler
    fake_inputs.__dict__["TokensPrompt"] = _StubTokensPrompt
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
    monkeypatch.setitem(sys.modules, "vllm.config", fake_config)
    monkeypatch.setitem(sys.modules, "vllm.inputs", fake_inputs)

    from codeintel_rev.io import vllm_engine as engine_module

    def _tokenizer_factory(*_: object, **__: object) -> _StubTokenizer:
        return _StubTokenizer()

    monkeypatch.setattr(
        engine_module,
        "AutoTokenizer",
        SimpleNamespace(from_pretrained=_tokenizer_factory),
        raising=False,
    )
    monkeypatch.setattr(engine_module, "TokensPrompt", _StubTokensPrompt, raising=False)
    monkeypatch.setattr(engine_module, "PoolerConfig", _StubPooler, raising=False)
    monkeypatch.setattr(engine_module, "LLM", _StubLLM, raising=False)


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
