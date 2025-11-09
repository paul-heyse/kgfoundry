from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from codeintel_rev.io import rerank_coderankllm as rerank_module
from codeintel_rev.io.rerank_coderankllm import CodeRankListwiseReranker


class _FakeTensor:
    def to(self, _device: str) -> _FakeTensor:
        return self


class _FakeTokenizer:
    def __init__(self, response: str) -> None:
        self.response = response
        self.decode_calls = 0

    def __call__(self, _prompt: str, *, return_tensors: str) -> dict[str, _FakeTensor]:
        assert return_tensors == "pt"
        return {"input_ids": _FakeTensor()}

    def decode(self, _output_ids: Any, *, skip_special_tokens: bool) -> str:
        assert skip_special_tokens
        self.decode_calls += 1
        return self.response


class _FakeModel:
    def __init__(self) -> None:
        self.generate_calls = 0

    def to(self, _device: str) -> _FakeModel:
        return self

    def eval(self) -> None:
        return None

    def generate(self, **_: Any) -> list[list[int]]:
        self.generate_calls += 1
        return [[0]]


def _patch_gate(monkeypatch: pytest.MonkeyPatch, tokenizer: _FakeTokenizer, model: _FakeModel) -> None:
    module = SimpleNamespace(
        AutoTokenizer=lambda *args, **kwargs: tokenizer,
        AutoModelForCausalLM=lambda *args, **kwargs: model,
    )

    def _gate_import(*_: object, **__: object) -> SimpleNamespace:
        return module

    monkeypatch.setattr(
        rerank_module,
        "gate_import",
        _gate_import,
    )


def test_reranker_reorders_when_json_valid(monkeypatch) -> None:
    tokenizer = _FakeTokenizer("[2, 1]")
    model = _FakeModel()
    _patch_gate(monkeypatch, tokenizer, model)
    reranker = CodeRankListwiseReranker(
        model_id="stub_valid",
        device="cpu",
        max_new_tokens=16,
        temperature=0.0,
        top_p=1.0,
    )

    result = reranker.rerank("query", [(1, "code1"), (2, "code2")])

    assert result == [2, 1]
    assert tokenizer.decode_calls == 1
    assert model.generate_calls == 1


def test_reranker_falls_back_on_invalid_output(monkeypatch) -> None:
    tokenizer = _FakeTokenizer("no json")
    model = _FakeModel()
    _patch_gate(monkeypatch, tokenizer, model)
    reranker = CodeRankListwiseReranker(
        model_id="stub_invalid",
        device="cpu",
        max_new_tokens=16,
        temperature=0.0,
        top_p=1.0,
    )

    result = reranker.rerank("query", [(1, "code1"), (2, "code2")])

    assert result == [1, 2]
