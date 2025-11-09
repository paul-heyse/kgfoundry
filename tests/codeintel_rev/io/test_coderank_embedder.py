from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest
from codeintel_rev.io.coderank_embedder import CodeRankEmbedder


class _FakeModel:
    def __init__(self) -> None:
        self.last_inputs: list[str] = []

    def encode(self, texts: list[str], **_: object) -> list[list[float]]:
        self.last_inputs = list(texts)
        return [[0.1, 0.2] for _ in texts]


def _patch_gate(monkeypatch: pytest.MonkeyPatch, fake_model: _FakeModel) -> None:
    def _build_model(*_: object, **__: object) -> _FakeModel:
        return fake_model

    module = SimpleNamespace(SentenceTransformer=_build_model)

    def _gate_import(*_: object, **__: object) -> SimpleNamespace:
        return module

    monkeypatch.setattr(
        "codeintel_rev.io.coderank_embedder.gate_import",
        _gate_import,
    )


def test_encode_queries_applies_instruction_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = _FakeModel()
    _patch_gate(monkeypatch, fake_model)

    settings = _EmbedderSettings(
        model_id="stub_queries",
        device="cpu",
        trust_remote_code=True,
        query_prefix="Represent this query: ",
        normalize=True,
        batch_size=4,
    )
    embedder = CodeRankEmbedder(settings=settings)
    vectors = embedder.encode_queries(["search scope"])

    assert fake_model.last_inputs[0].startswith("Represent this query: ")
    assert vectors.shape == (1, 2)
    assert vectors.dtype == np.float32


def test_encode_codes_requires_input(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = _FakeModel()
    _patch_gate(monkeypatch, fake_model)
    settings = _EmbedderSettings(
        model_id="stub_codes",
        device="cpu",
        trust_remote_code=True,
        query_prefix="prefix: ",
        normalize=True,
        batch_size=4,
    )
    embedder = CodeRankEmbedder(settings=settings)

    with pytest.raises(ValueError, match="code snippet"):
        embedder.encode_codes([])
@dataclass
class _EmbedderSettings:
    model_id: str
    device: str
    trust_remote_code: bool
    query_prefix: str
    normalize: bool
    batch_size: int
