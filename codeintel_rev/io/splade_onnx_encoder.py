"""ONNX-based SPLADE query encoders."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayAny

_np = LazyModule("numpy", "SPLADE ONNX encoder")
_ort = LazyModule("onnxruntime", "SPLADE ONNX encoder")
_transformers = LazyModule("transformers", "SPLADE ONNX encoder tokenizer")


class _OnnxOutput(Protocol):
    name: str


class _OnnxSession(Protocol):
    def run(
        self,
        output_names: Sequence[str] | None,
        feeds: Mapping[str, object],
    ) -> list[np.ndarray]: ...

    def get_outputs(self) -> Sequence[_OnnxOutput]: ...


class _TokenizerProtocol(Protocol):
    def __call__(self, text: str, **kwargs: object) -> dict[str, np.ndarray]: ...

    def convert_ids_to_tokens(self, ids: list[int]) -> list[str]: ...


SessionFactory = Callable[["OnnxSpladeConfig"], _OnnxSession]
TokenizerFactory = Callable[["OnnxSpladeConfig"], _TokenizerProtocol]


@dataclass(frozen=True, slots=True)
class OnnxSpladeConfig:
    """Configuration describing how to execute the SPLADE ONNX graph.

    Parameters
    ----------
    model_path :
        Path of the exported ONNX model.
    tokenizer_name :
        HuggingFace tokenizer identifier or path.
    output_name :
        Name of the logits tensor inside the graph.
    input_ids_name :
        Name of the tensor feeding token ids.
    attention_mask_name :
        Name of the attention mask tensor.
    providers :
        Tuple of ONNX Runtime execution providers.
    topn :
        Number of terms to keep after scoring.
    min_weight :
        Minimum score for a token to be retained.
    normalize :
        Whether to L2-normalize weights before returning them.
    """

    model_path: Path
    tokenizer_name: str
    output_name: str = "logits"
    input_ids_name: str = "input_ids"
    attention_mask_name: str = "attention_mask"
    providers: tuple[str, ...] = ("CPUExecutionProvider",)
    topn: int = 64
    min_weight: float = 1e-6
    normalize: bool = False


class _OnnxEncoderBase:
    """Shared helpers for SPLADE ONNX encoders."""

    __slots__ = (
        "_cfg",
        "_np_module",
        "_session",
        "_session_factory",
        "_tokenizer",
        "_tokenizer_factory",
    )

    def __init__(
        self,
        cfg: OnnxSpladeConfig,
        *,
        session_factory: SessionFactory | None = None,
        tokenizer_factory: TokenizerFactory | None = None,
        numpy_module: ModuleType | None = None,
    ) -> None:
        self._cfg = cfg
        self._session_factory = session_factory
        self._tokenizer_factory = tokenizer_factory
        self._np_module = numpy_module
        self._session: _OnnxSession | None = None
        self._tokenizer: _TokenizerProtocol | None = None

    def _np(self) -> ModuleType:
        return self._np_module or _np.module()

    def _load_session(self) -> _OnnxSession:
        if self._session is not None:
            return self._session
        if self._session_factory is not None:
            session = self._session_factory(self._cfg)
        else:
            session = _ort.module().InferenceSession(
                str(self._cfg.model_path),
                providers=list(self._cfg.providers),
            )
        self._session = session
        return session

    def _load_tokenizer(self) -> _TokenizerProtocol:
        if self._tokenizer is not None:
            return self._tokenizer
        if self._tokenizer_factory is not None:
            tokenizer = self._tokenizer_factory(self._cfg)
        else:
            tokenizer = _transformers.module().AutoTokenizer.from_pretrained(
                self._cfg.tokenizer_name,
                use_fast=True,
            )
        self._tokenizer = tokenizer
        return tokenizer

    def _impact_terms(self, text: str) -> tuple[list[str], Sequence[float]]:
        session = self._load_session()
        tokenizer = self._load_tokenizer()
        np_mod = self._np()
        feeds = self._build_feeds(tokenizer, text)
        outputs = session.run(None, feeds)
        vector = self._select_vector(session, outputs)
        clipped = self._clip_vector(np_mod, vector)
        return self._top_terms(tokenizer, np_mod, clipped)

    def _build_feeds(self, tokenizer: _TokenizerProtocol, text: str) -> dict[str, object]:
        encoded = tokenizer(
            text,
            truncation=True,
            padding=False,
            max_length=256,
            return_tensors="np",
        )
        feeds: dict[str, object] = {}
        feeds[self._cfg.input_ids_name] = encoded.get("input_ids", encoded["input_ids"])
        if self._cfg.attention_mask_name:
            mask_value = encoded.get("attention_mask")
            if mask_value is None:
                mask_value = encoded.get(self._cfg.attention_mask_name)
            if mask_value is not None:
                feeds[self._cfg.attention_mask_name] = mask_value
        return feeds

    def _select_vector(self, session: _OnnxSession, outputs: Sequence[object]) -> object:
        names = [out.name for out in session.get_outputs()]
        for name, value in zip(names, outputs, strict=False):
            if name == self._cfg.output_name:
                return value
        return outputs[0]

    @staticmethod
    def _clip_vector(np_mod: ModuleType, vector: object) -> NDArrayAny:
        arr = np_mod.asarray(vector, dtype=np_mod.float32)
        if arr.ndim > 1:
            arr = arr.reshape(arr.shape[-1])
        return np_mod.maximum(arr, 0.0)

    def _top_terms(
        self,
        tokenizer: _TokenizerProtocol,
        np_mod: ModuleType,
        clipped: NDArrayAny,
    ) -> tuple[list[str], Sequence[float]]:
        dimension = int(clipped.shape[-1])
        if dimension == 0:
            return [], []
        topn = max(1, min(int(self._cfg.topn), dimension))
        indices = np_mod.argpartition(-clipped, topn - 1)[:topn]
        weights = clipped[indices]
        if self._cfg.normalize and weights.size:
            norm = float(np_mod.linalg.norm(weights))
            if norm > 0:
                weights /= norm
        tokens = tokenizer.convert_ids_to_tokens(indices.tolist())
        filtered_tokens: list[str] = []
        filtered_weights: list[float] = []
        for token, weight in zip(tokens, weights, strict=False):
            score = float(weight)
            if score >= self._cfg.min_weight:
                filtered_tokens.append(token)
                filtered_weights.append(score)
        return filtered_tokens, filtered_weights


class OnnxSpladeQueryEncoder(_OnnxEncoderBase):
    """Return weighted-string representations suitable for LuceneImpactSearcher."""

    def encode(self, text: str) -> str:
        """Encode ``text`` as ``term^weight`` pairs.

        Parameters
        ----------
        text : str
            Query text to encode.

        Returns
        -------
        str
            Space-separated string of "term^weight" pairs.
        """
        tokens, weights = self._impact_terms(text)
        parts = [f"{token}^{weight:.6f}" for token, weight in zip(tokens, weights, strict=False)]
        return " ".join(parts)


class OnnxSpladeMapEncoder(_OnnxEncoderBase):
    """Return mapping representations consumed by Lucene impact searchers."""

    def encode_to_impact(self, text: str) -> dict[str, float]:
        """Encode ``text`` as a mapping of tokens to weights.

        Parameters
        ----------
        text : str
            Query text to encode.

        Returns
        -------
        dict[str, float]
            Dictionary mapping token strings to their weights.
        """
        tokens, weights = self._impact_terms(text)
        return {token: float(weight) for token, weight in zip(tokens, weights, strict=False)}


__all__ = [
    "OnnxSpladeConfig",
    "OnnxSpladeMapEncoder",
    "OnnxSpladeQueryEncoder",
]
