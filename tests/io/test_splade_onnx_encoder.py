"""Tests for the ONNX-based SPLADE query encoders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from codeintel_rev.io.splade_onnx_encoder import (
    OnnxSpladeConfig,
    OnnxSpladeMapEncoder,
    OnnxSpladeQueryEncoder,
)

from tests._helpers import assertions


@dataclass(slots=True, frozen=True)
class _StubOutput:
    """Stub ONNX output for testing."""

    name: str


class _StubSession:
    """Stub ONNX session for testing SPLADE encoder."""

    def __init__(self) -> None:
        """Initialize stub session with logits output."""
        self._outputs = [_StubOutput("logits")]
        self.invocations = 0

    def run(
        self,
        output_names: Sequence[str] | None,
        feeds: Mapping[str, object],
    ) -> list[np.ndarray]:
        """Return synthetic logits for the encoder under test.

        Returns
        -------
        list[np.ndarray]
            Single-element list containing synthetic logits.
        """
        _ = (output_names, feeds)
        self.invocations += 1
        return [np.linspace(0.1, 0.6, num=6, dtype=np.float32)]

    def get_outputs(self) -> list[_StubOutput]:
        """Return stub output list.

        Returns
        -------
        list[_StubOutput]
            List containing single stub output with name "logits".
        """
        return self._outputs


class _StubTokenizer:
    """Stub tokenizer for testing SPLADE encoder."""

    def __init__(self) -> None:
        """Initialize stub tokenizer with call counters."""
        self.calls = 0
        self.conversions = 0

    def __call__(self, text: str, **_kwargs: object) -> dict[str, np.ndarray]:
        self.calls += 1
        _ = text
        ids = np.arange(6, dtype=np.int64).reshape(1, -1)
        mask = np.ones_like(ids)
        return {"input_ids": ids, "attention_mask": mask}

    def convert_ids_to_tokens(self, ids: list[int]) -> list[str]:
        """Convert token IDs to token strings.

        Parameters
        ----------
        ids : list[int]
            List of token IDs to convert.

        Returns
        -------
        list[str]
            List of token strings prefixed with "t".
        """
        self.conversions += 1
        return [f"t{idx}" for idx in ids]


def test_onnx_query_encoder_builds_weighted_string() -> None:
    """Test that ONNX query encoder produces weighted string output."""
    cfg = OnnxSpladeConfig(model_path=Path("model.onnx"), tokenizer_name="stub")
    encoder = OnnxSpladeQueryEncoder(
        cfg,
        session_factory=lambda _cfg: cast("Any", _StubSession()),
        tokenizer_factory=lambda _cfg: _StubTokenizer(),
        numpy_module=np,
    )

    output = encoder.encode("hybrid search")

    assertions.expect_true(output.startswith("t"))
    assertions.expect_true("^" in output)


def test_onnx_map_encoder_returns_mapping() -> None:
    """Test that ONNX map encoder returns token-to-weight mapping."""
    cfg = OnnxSpladeConfig(model_path=Path("model.onnx"), tokenizer_name="stub", topn=3)
    encoder = OnnxSpladeMapEncoder(
        cfg,
        session_factory=lambda _cfg: cast("Any", _StubSession()),
        tokenizer_factory=lambda _cfg: _StubTokenizer(),
        numpy_module=np,
    )

    mapping = encoder.encode_to_impact("bm25 + splade")

    assertions.expect_equal(len(mapping), cfg.topn)
    for token, weight in mapping.items():
        assertions.expect_true(token.startswith("t"))
        assertions.expect_true(weight >= cfg.min_weight)
