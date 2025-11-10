"""In-process vLLM embedding engine for Stage-0 retrieval."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np
from transformers import AutoTokenizer, PreTrainedTokenizerBase
from vllm import LLM
from vllm.config import PoolerConfig
from vllm.inputs import TokensPrompt

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.config.settings import VLLMConfig

LOGGER = get_logger(__name__)


class _InprocessVLLMRuntime:
    """Mutable runtime backing the frozen embedder."""

    __slots__ = ("engine", "tokenizer")

    def __init__(self) -> None:
        self.tokenizer: PreTrainedTokenizerBase | None = None
        self.engine: LLM | None = None


@dataclass(slots=True, frozen=True)
class InprocessVLLMEmbedder:
    """Embed text batches locally using vLLM.

    Parameters
    ----------
    config : VLLMConfig
        Fully populated vLLM configuration. The ``run.mode`` field must be
        ``"inprocess"`` to avoid HTTP calls.

    Examples
    --------
    >>> from codeintel_rev.config.settings import VLLMConfig, VLLMRunMode
    >>> cfg = VLLMConfig(run=VLLMRunMode(mode="inprocess"))
    >>> embedder = InprocessVLLMEmbedder(cfg)
    >>> vecs = embedder.embed_batch(["hello world"])
    >>> vecs.shape[0]
    1
    """

    config: VLLMConfig
    _runtime: _InprocessVLLMRuntime = field(
        default_factory=_InprocessVLLMRuntime, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Initialize tokenizer and vLLM engine."""
        os.environ.setdefault("VLLM_ATTENTION_BACKEND", "FLASHINFER")
        runtime = self._runtime
        runtime.tokenizer = self._load_tokenizer()
        runtime.engine = self._load_engine()
        LOGGER.info(
            "Initialized in-process vLLM embedder",
            extra={
                "model": self.config.model,
                "pooling": self.config.pooling_type,
                "normalize": self.config.normalize,
            },
        )

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return embeddings for ``texts`` (shape ``[N, dim]``).

        Parameters
        ----------
        texts : Sequence[str]
            Ordered text payload to embed.

        Returns
        -------
        np.ndarray
            Embedding matrix aligned with the input order.

        Raises
        ------
        RuntimeError
            If the vLLM runtime failed to initialize.
        """
        if not texts:
            return np.zeros((0, self.config.embedding_dim), dtype=np.float32)
        runtime = self._ensure_runtime()
        tokenizer = runtime.tokenizer
        engine = runtime.engine
        if tokenizer is None or engine is None:  # pragma: no cover - defensive
            msg = "vLLM runtime not initialized"
            raise RuntimeError(msg)
        inputs = tokenizer(
            list(texts),
            padding=False,
            truncation=True,
            return_tensors=None,
        )
        raw_input_ids = inputs.get("input_ids")
        if raw_input_ids is None:
            msg = "Tokenizer did not return input_ids"
            raise RuntimeError(msg)
        token_sequences = cast("Sequence[Sequence[int]]", raw_input_ids)
        prompts: list[TokensPrompt] = [
            TokensPrompt(prompt_token_ids=list(map(int, ids))) for ids in token_sequences
        ]
        outputs = engine.embed(prompts)
        vectors = np.asarray(
            [item.outputs.embedding for item in outputs],
            dtype=np.float32,
        )
        if vectors.shape[1] != self.config.embedding_dim:
            LOGGER.warning(
                "vLLM embedding dimension mismatch",
                extra={
                    "expected": self.config.embedding_dim,
                    "observed": vectors.shape[1],
                },
            )
        return vectors

    def close(self) -> None:  # pragma: no cover - best-effort cleanup
        """Release tokenizer/engine references to help GC."""
        runtime = self._runtime
        runtime.engine = None
        runtime.tokenizer = None

    def _load_tokenizer(self) -> PreTrainedTokenizerBase:
        return AutoTokenizer.from_pretrained(
            self.config.model,
            trust_remote_code=True,
        )

    def _load_engine(self) -> LLM:
        return LLM(
            model=self.config.model,
            task="embed",
            trust_remote_code=True,
            enforce_eager=True,
            gpu_memory_utilization=self.config.gpu_memory_utilization,
            max_num_batched_tokens=self.config.max_num_batched_tokens,
            override_pooler_config=PoolerConfig(
                pooling_type=self.config.pooling_type,
                normalize=self.config.normalize,
            ),
        )

    def _ensure_runtime(self) -> _InprocessVLLMRuntime:
        """Ensure tokenizer and engine exist, lazily creating them if needed.

        Returns
        -------
        _InprocessVLLMRuntime
            Mutable runtime container with initialized tokenizer/engine.
        """
        runtime = self._runtime
        if runtime.tokenizer is None:
            runtime.tokenizer = self._load_tokenizer()
        if runtime.engine is None:
            runtime.engine = self._load_engine()
        return runtime


__all__ = ["InprocessVLLMEmbedder"]
