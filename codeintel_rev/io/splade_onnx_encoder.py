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
    """Protocol describing an ONNX model output tensor.

    Attributes
    ----------
    name : str
        Name of the output tensor in the ONNX graph.
    """

    name: str


class _OnnxSession(Protocol):
    """Protocol describing the ONNX Runtime InferenceSession interface.

    This protocol abstracts the ONNX Runtime API to enable type-safe interaction
    with ONNX model execution while maintaining compatibility across different
    ONNX Runtime versions.
    """

    def run(
        self,
        output_names: Sequence[str] | None,
        feeds: Mapping[str, object],
    ) -> list[np.ndarray]:
        """Execute the ONNX model with provided input feeds.

        Parameters
        ----------
        output_names : Sequence[str] | None
            Names of output tensors to retrieve. If None, returns all outputs.
        feeds : Mapping[str, object]
            Dictionary mapping input tensor names to their values (typically
            numpy arrays).

        Returns
        -------
        list[np.ndarray]
            List of output tensors as numpy arrays, ordered by output_names
            or the model's default output order.
        """
        ...

    def get_outputs(self) -> Sequence[_OnnxOutput]:
        """Retrieve metadata for all model outputs.

        Returns
        -------
        Sequence[_OnnxOutput]
            Sequence of output metadata objects describing each output tensor.
        """
        ...


class _TokenizerProtocol(Protocol):
    """Protocol describing a HuggingFace tokenizer interface.

    This protocol abstracts tokenizer functionality to enable type-safe
    interaction with tokenization while maintaining compatibility across
    different tokenizer implementations.
    """

    def __call__(self, text: str, **kwargs: object) -> dict[str, np.ndarray]:
        """Tokenize text into model inputs.

        Parameters
        ----------
        text : str
            Text to tokenize.
        **kwargs : object
            Additional tokenization options (e.g., truncation, padding,
            max_length, return_tensors).

        Returns
        -------
        dict[str, np.ndarray]
            Dictionary containing tokenized inputs, typically with keys like
            "input_ids" and "attention_mask", mapped to numpy arrays.
        """
        ...

    def convert_ids_to_tokens(self, ids: list[int]) -> list[str]:
        """Convert token IDs back to token strings.

        Parameters
        ----------
        ids : list[int]
            List of token IDs to convert.

        Returns
        -------
        list[str]
            List of token strings corresponding to the input IDs.
        """
        ...


SessionFactory = Callable[["OnnxSpladeConfig"], _OnnxSession]
TokenizerFactory = Callable[["OnnxSpladeConfig"], _TokenizerProtocol]


@dataclass(frozen=True, slots=True)
class OnnxSpladeConfig:
    """Configuration describing how to execute the SPLADE ONNX graph.

    Attributes
    ----------
    model_path : Path
        Path of the exported ONNX model file.
    tokenizer_name : str
        HuggingFace tokenizer identifier or local path.
    output_name : str
        Name of the logits tensor inside the ONNX graph.
    input_ids_name : str
        Name of the tensor feeding token IDs to the graph.
    attention_mask_name : str
        Name of the attention mask tensor in the graph.
    providers : tuple[str, ...]
        Tuple of ONNX Runtime execution providers (e.g., "CPUExecutionProvider").
    topn : int
        Maximum number of top tokens to extract from SPLADE logits. Must be
        positive.
    min_weight : float
        Minimum score threshold for a token to be retained. Tokens below this
        threshold are discarded. Must be non-negative.
    normalize : bool
        Whether to L2-normalize token weights before returning them.
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
        """Initialize the base ONNX encoder with configuration and factories.

        Parameters
        ----------
        cfg : OnnxSpladeConfig
            Configuration describing the ONNX model, tokenizer, and execution
            parameters.
        session_factory : SessionFactory | None, optional
            Factory function for creating ONNX Runtime sessions. If None,
            uses the default ONNX Runtime InferenceSession constructor.
        tokenizer_factory : TokenizerFactory | None, optional
            Factory function for creating tokenizers. If None, uses HuggingFace
            AutoTokenizer.from_pretrained.
        numpy_module : ModuleType | None, optional
            NumPy module to use for array operations. If None, uses the lazy-loaded
            numpy module. Useful for testing with mock numpy implementations.
        """
        self._cfg = cfg
        self._session_factory = session_factory
        self._tokenizer_factory = tokenizer_factory
        self._np_module = numpy_module
        self._session: _OnnxSession | None = None
        self._tokenizer: _TokenizerProtocol | None = None

    def _np(self) -> ModuleType:
        """Return the NumPy module for array operations.

        Returns
        -------
        ModuleType
            The NumPy module instance, either from initialization or lazy-loaded.
        """
        return self._np_module or _np.module()

    def _load_session(self) -> _OnnxSession:
        """Load or return a cached ONNX Runtime inference session.

        Returns
        -------
        _OnnxSession
            An ONNX Runtime inference session bound to the configured model path
            and execution providers. The session is cached after first creation.
        """
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
        """Load or return a cached tokenizer instance.

        Returns
        -------
        _TokenizerProtocol
            A HuggingFace tokenizer instance configured with the tokenizer name
            from configuration. The tokenizer is cached after first creation.
        """
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
        """Extract top impact terms and weights from text using SPLADE encoding.

        Parameters
        ----------
        text : str
            Text to encode and extract impact terms from.

        Returns
        -------
        tuple[list[str], Sequence[float]]
            A tuple containing (terms, weights) where terms is a list of token
            strings and weights is a sequence of corresponding importance scores.
            Terms are filtered by min_weight and limited to topn based on configuration.
        """
        session = self._load_session()
        tokenizer = self._load_tokenizer()
        np_mod = self._np()
        feeds = self._build_feeds(tokenizer, text)
        outputs = session.run(None, feeds)
        vector = self._select_vector(session, outputs)
        clipped = self._clip_vector(np_mod, vector)
        return self._top_terms(tokenizer, np_mod, clipped)

    def _build_feeds(self, tokenizer: _TokenizerProtocol, text: str) -> dict[str, object]:
        """Build ONNX input feeds from tokenized text.

        Parameters
        ----------
        tokenizer : _TokenizerProtocol
            Tokenizer instance to encode the text.
        text : str
            Text to tokenize and prepare as model inputs.

        Returns
        -------
        dict[str, object]
            Dictionary mapping ONNX input tensor names to their values (numpy
            arrays). Contains input_ids and optionally attention_mask based on
            configuration.
        """
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
        """Select the output vector matching the configured output name.

        Parameters
        ----------
        session : _OnnxSession
            ONNX session to query for output metadata.
        outputs : Sequence[object]
            Sequence of output tensors from model execution.

        Returns
        -------
        object
            The output tensor matching the configured output_name, or the first
            output if no match is found.
        """
        names = [out.name for out in session.get_outputs()]
        for name, value in zip(names, outputs, strict=False):
            if name == self._cfg.output_name:
                return value
        return outputs[0]

    @staticmethod
    def _clip_vector(np_mod: ModuleType, vector: object) -> NDArrayAny:
        """Clip vector values to non-negative and flatten if needed.

        Parameters
        ----------
        np_mod : ModuleType
            NumPy module for array operations.
        vector : object
            Vector tensor to clip, can be multi-dimensional.

        Returns
        -------
        NDArrayAny
            A flattened float32 array with all negative values clipped to zero.
        """
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
        """Extract top terms and weights from a clipped impact vector.

        Parameters
        ----------
        tokenizer : _TokenizerProtocol
            Tokenizer to convert token IDs back to token strings.
        np_mod : ModuleType
            NumPy module for array operations.
        clipped : NDArrayAny
            Clipped impact vector with non-negative values.

        Returns
        -------
        tuple[list[str], Sequence[float]]
            A tuple containing (terms, weights) where terms is a list of token
            strings and weights is a sequence of corresponding importance scores.
            Terms are filtered by min_weight and limited to topn based on configuration.
            Weights may be L2-normalized if normalize is enabled.
        """
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
