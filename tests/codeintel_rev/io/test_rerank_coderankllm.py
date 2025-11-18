"""Tests for the CodeRank LLAMA-based reranker shim."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codeintel_rev.io.rerank_coderankllm import (
    CodeRankGenerationSettings,
    CodeRankListwiseReranker,
    CoderankLLMRerankerContext,
)

from tests._helpers import assertions

if TYPE_CHECKING:
    from transformers import AutoModelForCausalLM, PreTrainedTokenizerBase
else:  # pragma: no cover - tests avoid importing heavy deps at runtime

    class PreTrainedTokenizerBase:
        """Runtime stub matching the tokenizer protocol."""

    class AutoModelForCausalLM:
        """Runtime stub matching the model protocol."""


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


def _build_context(tokenizer: _FakeTokenizer, model: _FakeModel) -> CoderankLLMRerankerContext:
    def _tokenizer_factory(_model_id: str) -> PreTrainedTokenizerBase:
        return cast("PreTrainedTokenizerBase", tokenizer)

    def _model_factory(_model_id: str) -> AutoModelForCausalLM:
        return cast("AutoModelForCausalLM", model)

    return CoderankLLMRerankerContext(
        tokenizer_factory=_tokenizer_factory,
        model_factory=_model_factory,
    )


def test_reranker_reorders_when_json_valid() -> None:
    """Valid JSON output produces reordered identifiers."""
    tokenizer = _FakeTokenizer("[2, 1]")
    model = _FakeModel()
    reranker_context = _build_context(tokenizer, model)
    reranker = CodeRankListwiseReranker(
        model_id="stub_valid",
        device="cpu",
        settings=CodeRankGenerationSettings(
            max_new_tokens=16,
            temperature=0.0,
            top_p=1.0,
        ),
        context=reranker_context,
    )

    result = reranker.rerank("query", [(1, "code1"), (2, "code2")])

    assertions.expect_sequence_equal(result, [2, 1])
    assertions.expect_equal(tokenizer.decode_calls, 1)
    assertions.expect_equal(model.generate_calls, 1)


def test_reranker_falls_back_on_invalid_output() -> None:
    """Invalid JSON preserves the original ordering."""
    tokenizer = _FakeTokenizer("no json")
    model = _FakeModel()
    reranker_context = _build_context(tokenizer, model)
    reranker = CodeRankListwiseReranker(
        model_id="stub_invalid",
        device="cpu",
        settings=CodeRankGenerationSettings(
            max_new_tokens=16,
            temperature=0.0,
            top_p=1.0,
        ),
        context=reranker_context,
    )

    result = reranker.rerank("query", [(1, "code1"), (2, "code2")])

    assertions.expect_sequence_equal(result, [1, 2])
