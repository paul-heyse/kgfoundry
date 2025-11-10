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

from codeintel_rev.runtime import RuntimeCell
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

    def close(self) -> None:  # pragma: no cover - exercised during shutdown
        """Release tokenizer/engine references."""
        if self.engine is not None:
            shutdown = getattr(self.engine, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:  # lint-ignore[BLE001] best-effort shutdown; log and continue
                    LOGGER.warning("vLLM engine shutdown failed", exc_info=True)
        self.engine = None
        self.tokenizer = None


@dataclass(slots=True, frozen=True)
class InprocessVLLMEmbedder:
    """Embed text batches locally using vLLM.

    Extended Summary
    ----------------
    This embedder provides in-process embedding generation using vLLM, enabling
    high-throughput batch embedding without HTTP overhead. It initializes a local
    vLLM engine with the specified model and pooling configuration, tokenizes input
    texts, and generates embeddings via vLLM's embedding API. The embedder is used
    in Stage-0 retrieval pipelines when vLLM is available and in-process mode is
    preferred over HTTP-based embedding services.

    Attributes
    ----------
    config : VLLMConfig
        Fully populated vLLM configuration. The ``run.mode`` field must be
        ``"inprocess"`` to avoid HTTP calls. Contains model path, pooling type,
        normalization settings, and GPU memory configuration.

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
    _cell: RuntimeCell[_InprocessVLLMRuntime] = field(
        default_factory=lambda: RuntimeCell(name="inprocess-vllm"),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Initialize tokenizer and vLLM engine."""
        os.environ.setdefault("VLLM_ATTENTION_BACKEND", "FLASHINFER")
        LOGGER.info(
            "Prepared in-process vLLM embedder configuration",
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
        runtime = self._runtime()
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
        self._cell.close()

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

    def _initialize_runtime(self) -> _InprocessVLLMRuntime:
        runtime = _InprocessVLLMRuntime()
        runtime.tokenizer = self._load_tokenizer()
        runtime.engine = self._load_engine()
        LOGGER.info(
            "Initialized in-process vLLM runtime",
            extra={
                "model": self.config.model,
                "pooling": self.config.pooling_type,
                "normalize": self.config.normalize,
            },
        )
        return runtime

    def _runtime(self) -> _InprocessVLLMRuntime:
        runtime = self._cell.get_or_initialize(self._initialize_runtime)
        if runtime.tokenizer is None or runtime.engine is None:  # pragma: no cover - defensive
            msg = "vLLM runtime not initialized"
            raise RuntimeError(msg)
        return runtime


__all__ = ["InprocessVLLMEmbedder"]
