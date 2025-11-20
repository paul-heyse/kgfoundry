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
    """Fake tensor stub for testing."""

    def to(self, _device: str) -> _FakeTensor:
        """Move tensor to device (no-op for stub).

        Parameters
        ----------
        _device : str
            Device name (unused).

        Returns
        -------
        _FakeTensor
            Self for chaining.
        """
        return self


class _FakeTokenizer:
    """Fake tokenizer for testing CodeRank reranker."""

    def __init__(self, response: str) -> None:
        """Initialize fake tokenizer with response string.

        Parameters
        ----------
        response : str
            Response string to return from decode.
        """
        self.response = response
        self.decode_calls = 0

    def __call__(self, _prompt: str, *, return_tensors: str) -> dict[str, _FakeTensor]:
        assertions.expect_equal(return_tensors, "pt")
        return {"input_ids": _FakeTensor()}

    def decode(self, _output_ids: object, *, skip_special_tokens: bool) -> str:
        """Decode token IDs to string and track call count.

        Parameters
        ----------
        _output_ids : object
            Token IDs to decode (unused).
        skip_special_tokens : bool
            Whether to skip special tokens (must be True).

        Returns
        -------
        str
            Pre-configured response string.
        """
        assertions.expect_true(skip_special_tokens)
        self.decode_calls += 1
        return self.response


class _FakeModel:
    """Fake model for testing CodeRank reranker."""

    def __init__(self) -> None:
        """Initialize fake model with generate call counter."""
        self.generate_calls = 0

    def to(self, _device: str) -> _FakeModel:
        """Move model to device (no-op for stub).

        Parameters
        ----------
        _device : str
            Device name (unused).

        Returns
        -------
        _FakeModel
            Self for chaining.
        """
        return self

    @staticmethod
    def eval() -> None:
        """Set model to evaluation mode (no-op for stub)."""
        return

    def generate(self, **_: object) -> list[list[int]]:
        """Generate token IDs and track call count.

        Parameters
        ----------
        **_ : object
            Generation parameters (unused).

        Returns
        -------
        list[list[int]]
            Stub token IDs [[0]].
        """
        self.generate_calls += 1
        return [[0]]


def _build_context(tokenizer: _FakeTokenizer, model: _FakeModel) -> CoderankLLMRerankerContext:
    """Build reranker context with fake tokenizer and model.

    Parameters
    ----------
    tokenizer : _FakeTokenizer
        Fake tokenizer instance.
    model : _FakeModel
        Fake model instance.

    Returns
    -------
    CoderankLLMRerankerContext
        Context with fake factories.
    """

    def _tokenizer_factory(_model_id: str) -> PreTrainedTokenizerBase:
        """Return fake tokenizer ignoring model_id.

        Parameters
        ----------
        _model_id : str
            Model ID (ignored).

        Returns
        -------
        PreTrainedTokenizerBase
            Fake tokenizer instance.
        """
        return cast("PreTrainedTokenizerBase", tokenizer)

    def _model_factory(_model_id: str) -> AutoModelForCausalLM:
        """Return fake model ignoring model_id.

        Parameters
        ----------
        _model_id : str
            Model ID (ignored).

        Returns
        -------
        AutoModelForCausalLM
            Fake model instance.
        """
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
