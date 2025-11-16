"""Tests for the CodeRank LLAMA-based reranker shim."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from codeintel_rev.io import rerank_coderankllm as rerank_module
from codeintel_rev.io.rerank_coderankllm import CodeRankListwiseReranker

from tests._helpers import assertions


class _FakeTensor:
    def to(self, _device: str) -> _FakeTensor:
        return self


class _FakeTokenizer:
    def __init__(self, response: str) -> None:
        self.response = response
        self.decode_calls = 0

    def __call__(self, _prompt: str, *, return_tensors: str) -> dict[str, _FakeTensor]:
        assertions.expect_equal(return_tensors, "pt")
        return {"input_ids": _FakeTensor()}

    def decode(self, _output_ids: object, *, skip_special_tokens: bool) -> str:
        assertions.expect_true(skip_special_tokens)
        self.decode_calls += 1
        return self.response


class _FakeModel:
    def __init__(self) -> None:
        self.generate_calls = 0

    def to(self, _device: str) -> _FakeModel:
        return self

    @staticmethod
    def eval() -> None:
        return None

    def generate(self, **_: object) -> list[list[int]]:
        self.generate_calls += 1
        return [[0]]


def _patch_gate(
    monkeypatch: pytest.MonkeyPatch, tokenizer: _FakeTokenizer, model: _FakeModel
) -> None:
    class _Factory:
        def __init__(self, instance: object) -> None:
            self._instance = instance

        def from_pretrained(self, *_args: object, **kwargs: object) -> object:
            del kwargs
            return self._instance

    module = SimpleNamespace(
        AutoTokenizer=_Factory(tokenizer),
        AutoModelForCausalLM=_Factory(model),
    )

    def _gate_import(*_: object, **__: object) -> SimpleNamespace:
        return module

    monkeypatch.setattr(
        rerank_module,
        "gate_import",
        _gate_import,
    )


def test_reranker_reorders_when_json_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid JSON output produces reordered identifiers."""
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

    assertions.expect_sequence_equal(result, [2, 1])
    assertions.expect_equal(tokenizer.decode_calls, 1)
    assertions.expect_equal(model.generate_calls, 1)


def test_reranker_falls_back_on_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid JSON preserves the original ordering."""
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

    assertions.expect_sequence_equal(result, [1, 2])
