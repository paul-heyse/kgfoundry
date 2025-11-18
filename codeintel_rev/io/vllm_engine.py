"""In-process vLLM embedding engine for Stage-0 retrieval."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.runtime import RuntimeCell
from codeintel_rev.typing import NDArrayF32


class TokenizerProtocol(Protocol):
    """Callable tokenizer interface used by the in-process embedder."""

    def __call__(self, texts: Sequence[str], **kwargs: object) -> dict[str, Any]: ...


class TokensPrompt(Protocol):
    """Structured prompt container used by vLLM embeddings."""

    prompt_token_ids: list[int]


class _EmbeddingOutput(Protocol):
    """Protocol for embedding output containing vector sequence."""

    embedding: Sequence[float]


class _EmbeddingResult(Protocol):
    """Protocol for embedding result containing output wrapper."""

    outputs: _EmbeddingOutput


class LLM(Protocol):
    """Interface for the vLLM embedding runtime."""

    def embed(self, prompts: Sequence[TokensPrompt]) -> Sequence[_EmbeddingResult]:
        """Generate embeddings for tokenized prompts.

        Parameters
        ----------
        prompts : Sequence[TokensPrompt]
            Sequence of tokenized prompts to embed.

        Returns
        -------
        Sequence[_EmbeddingResult]
            Sequence of embedding results, one per prompt.
        """
        ...

    def shutdown(self) -> None:
        """Shutdown the LLM engine and release resources."""
        ...


class PoolerConfig(Protocol):
    """Structured pooler configuration for vLLM."""

    def __init__(self, **kwargs: object) -> None: ...


if TYPE_CHECKING:
    import numpy as np

    from codeintel_rev.config.settings import VLLMConfig

    transformers = cast("Any", None)
    vllm = cast("Any", None)
    vllm_config = cast("Any", None)
    vllm_inputs = cast("Any", None)

else:  # pragma: no cover - runtime imports
    try:
        import numpy as np
    except ImportError:
        np = cast("Any", LazyModule("numpy", "in-process vLLM embeddings"))

    try:
        import transformers
    except ImportError:
        transformers = cast("Any", LazyModule("transformers", "in-process vLLM tokenizer"))

    try:
        import vllm
        import vllm.config as vllm_config
        import vllm.inputs as vllm_inputs
    except ImportError:
        vllm = cast("Any", LazyModule("vllm", "in-process vLLM runtime"))
        vllm_config = cast("Any", LazyModule("vllm.config", "in-process vLLM config"))
        vllm_inputs = cast("Any", LazyModule("vllm.inputs", "in-process vLLM prompts"))


class _InprocessVLLMRuntime:
    """Mutable runtime backing the frozen embedder."""

    __slots__ = ("engine", "tokenizer")

    def __init__(self) -> None:
        self.tokenizer: TokenizerProtocol | None = None
        self.engine: LLM | None = None

    def close(self) -> None:  # pragma: no cover - exercised during shutdown
        """Release tokenizer/engine references."""
        if self.engine is not None:
            shutdown = getattr(self.engine, "shutdown", None)
            if callable(shutdown):
                with suppress(RuntimeError, OSError, ValueError):
                    shutdown()
        self.engine = None
        self.tokenizer = None


@dataclass(slots=True, frozen=True)
class InprocessVLLMContext:
    """Dependency providers for in-process vLLM embeddings."""

    tokenizer_factory: Callable[[str], TokenizerProtocol]
    llm_factory: Callable[[VLLMConfig], LLM]
    tokens_prompt_factory: Callable[[Sequence[int]], TokensPrompt]

    @classmethod
    def production(cls) -> InprocessVLLMContext:
        """Return the production context using real vLLM modules.

        Returns
        -------
        InprocessVLLMContext
            Context configured with real tokenizer/LLM factories.
        """

        def _tokenizer(model_id: str) -> TokenizerProtocol:
            """Create AutoTokenizer instance from model ID.

            Parameters
            ----------
            model_id : str
                HuggingFace model identifier.

            Returns
            -------
            TokenizerProtocol
                Tokenizer instance loaded from model_id.
            """
            transformers_mod = cast("Any", transformers)
            tokenizer = transformers_mod.AutoTokenizer.from_pretrained(
                model_id,
                trust_remote_code=True,
            )
            return cast("TokenizerProtocol", tokenizer)

        def _llm(cfg: VLLMConfig) -> LLM:
            """Create vLLM LLM instance from configuration.

            Parameters
            ----------
            cfg : VLLMConfig
                vLLM configuration for model initialization.

            Returns
            -------
            LLM
                vLLM LLM instance configured with cfg.
            """
            llm_cls = cast("type[Any]", vllm.LLM)
            pooler_config_cls = cast("type[Any]", vllm_config.PoolerConfig)
            instance = llm_cls(
                model=cfg.model,
                trust_remote_code=True,
                enforce_eager=True,
                gpu_memory_utilization=cfg.memory_utilization,
                max_num_batched_tokens=cfg.max_num_batched_tokens,
                override_pooler_config=pooler_config_cls(**cfg.pooler_kwargs()),
            )
            return cast("LLM", instance)

        def _tokens_prompt(token_ids: Sequence[int]) -> TokensPrompt:
            """Create TokensPrompt instance from token ID sequence.

            Parameters
            ----------
            token_ids : Sequence[int]
                Sequence of token IDs to wrap in prompt.

            Returns
            -------
            TokensPrompt
                Prompt instance containing token IDs.
            """
            tokens_prompt_cls = cast("type[Any]", vllm_inputs.TokensPrompt)
            prompt = tokens_prompt_cls(prompt_token_ids=list(map(int, token_ids)))
            return cast("TokensPrompt", prompt)

        return cls(
            tokenizer_factory=_tokenizer,
            llm_factory=_llm,
            tokens_prompt_factory=_tokens_prompt,
        )


@dataclass(slots=True)
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
        normalization settings, and memory configuration for the embedding server.

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

    context: InprocessVLLMContext | None = None

    def __post_init__(self) -> None:
        """Initialize tokenizer and vLLM engine."""
        os.environ.setdefault("VLLM_ATTENTION_BACKEND", "FLASHINFER")
        if self.context is None:
            object.__setattr__(self, "context", InprocessVLLMContext.production())

    def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
        """Return embeddings for ``texts`` (shape ``[N, dim]``).

        This method generates embeddings for a batch of text inputs using the
        configured vLLM embedding model. It delegates to embed_batch_with_stats()
        and returns only the embedding vectors, discarding token count statistics.
        The embeddings are normalized if configured and ready for similarity
        computation or storage.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of text strings to embed. Each string is tokenized and passed
            through the vLLM embedding model to generate a dense vector representation.
            The batch is processed efficiently using vLLM's batched inference.

        Returns
        -------
        NDArrayF32
            Embedding matrix with shape `(N, dim)` where N is the number of input
            texts and dim is the embedding dimension (model-dependent). Dtype is
            float32. Embeddings are normalized if the normalize configuration is
            enabled, otherwise raw model outputs. The matrix is ready for similarity
            computation, storage, or indexing operations.
        """
        vectors, _ = self.embed_batch_with_stats(texts)
        return vectors

    def embed_batch_with_stats(self, texts: Sequence[str]) -> tuple[NDArrayF32, int]:
        """Return embeddings and total token count for ``texts``.

        Parameters
        ----------
        texts : Sequence[str]
            Ordered text payload to embed.

        Returns
        -------
        tuple[NDArrayF32, int]
            Tuple containing the embedding matrix and the total prompt token count.

        Raises
        ------
        RuntimeError
            If the vLLM runtime failed to initialize.
        """
        if not texts:
            empty = np.zeros((0, self.config.embedding_dim), dtype=np.float32)
            return empty, 0
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
        context = self._context()
        prompts = [context.tokens_prompt_factory(ids) for ids in token_sequences]
        total_tokens = sum(len(ids) for ids in token_sequences)
        outputs = engine.embed(prompts)
        vectors = np.asarray(
            [item.outputs.embedding for item in outputs],
            dtype=np.float32,
        )
        if vectors.shape[1] != self.config.embedding_dim:
            message = (
                "vLLM embedding dimension mismatch: "
                f"{vectors.shape[1]} != {self.config.embedding_dim}"
            )
            raise RuntimeError(message)
        return vectors, total_tokens

    def close(self) -> None:  # pragma: no cover - best-effort cleanup
        """Release tokenizer/engine references to help GC."""
        self._cell.close()

    def _initialize_runtime(self) -> _InprocessVLLMRuntime:
        """Initialize vLLM runtime with tokenizer and engine.

        Returns
        -------
        _InprocessVLLMRuntime
            Initialized runtime instance with tokenizer and engine loaded.
        """
        runtime = _InprocessVLLMRuntime()
        context = self._context()
        runtime.tokenizer = context.tokenizer_factory(self.config.model)
        runtime.engine = context.llm_factory(self.config)
        return runtime

    def _runtime(self) -> _InprocessVLLMRuntime:
        """Get or initialize vLLM runtime instance.

        Returns
        -------
        _InprocessVLLMRuntime
            Runtime instance with tokenizer and engine initialized.

        Raises
        ------
        RuntimeError
            If runtime initialization fails or tokenizer/engine are None.
        """
        runtime = self._cell.get_or_initialize(self._initialize_runtime)
        if runtime.tokenizer is None or runtime.engine is None:  # pragma: no cover - defensive
            msg = "vLLM runtime not initialized"
            raise RuntimeError(msg)
        return runtime

    def _context(self) -> InprocessVLLMContext:
        """Get in-process vLLM context instance.

        Returns
        -------
        InprocessVLLMContext
            Context instance with tokenizer/LLM factories.

        Raises
        ------
        RuntimeError
            If context is None.
        """
        context = self.context
        if context is None:  # pragma: no cover - defensive
            msg = "In-process vLLM context not initialized"
            raise RuntimeError(msg)
        return context


__all__ = ["InprocessVLLMEmbedder"]
