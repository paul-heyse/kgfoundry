"""Pooled wrapper around the CodeRank embedding SentenceTransformer."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.runtime.imports import gate_import
from codeintel_rev.typing import NDArrayF32

if TYPE_CHECKING:
    import numpy as np
    from sentence_transformers import SentenceTransformer
else:
    np = cast("np", LazyModule("numpy", "CodeRank embeddings"))
    SentenceTransformer = Any


class SupportsCodeRankSettings(Protocol):
    """Protocol describing the minimal settings required by the embedder."""

    @property
    def model_id(self) -> str:
        """CodeRank model identifier."""
        ...

    @property
    def device(self) -> str:
        """Target device for inference."""
        ...

    @property
    def trust_remote_code(self) -> bool:
        """Whether to trust remote code when loading the model."""
        ...

    @property
    def query_prefix(self) -> str:
        """Instruction prefix required by the model."""
        ...

    @property
    def normalize(self) -> bool:
        """Whether embeddings should be normalized."""
        ...

    @property
    def batch_size(self) -> int:
        """Batch size used when encoding queries."""
        ...


class SentenceEncoderProtocol(Protocol):
    """Minimal interface required from embedding backends."""

    def encode(
        self,
        texts: Iterable[str],
        *,
        normalize_embeddings: bool,
        batch_size: int,
    ) -> NDArrayF32 | Sequence[Sequence[float]]:
        """Return embeddings for ``texts``."""
        ...


@dataclass(slots=True, frozen=True)
class CodeRankEmbedderContext:
    """Dependency providers for the CodeRank embedder.

    Attributes
    ----------
    model_provider : Callable[[SupportsCodeRankSettings], SentenceEncoderProtocol]
        Factory function that creates a SentenceEncoderProtocol instance from
        CodeRank settings. Used for dependency injection in tests.
    """

    model_provider: Callable[[SupportsCodeRankSettings], SentenceEncoderProtocol]

    @classmethod
    def production(cls) -> CodeRankEmbedderContext:
        """Return the default production context.

        Returns
        -------
        CodeRankEmbedderContext
            Context configured to load SentenceTransformer via ``gate_import``.
        """

        def _provider(settings: SupportsCodeRankSettings) -> SentenceEncoderProtocol:
            """Create a SentenceTransformer instance from settings.

            Parameters
            ----------
            settings : SupportsCodeRankSettings
                Settings containing model ID, device, and trust_remote_code flag.

            Returns
            -------
            SentenceEncoderProtocol
                SentenceTransformer instance cast to protocol.

            Raises
            ------
            RuntimeError
                If sentence_transformers module doesn't expose SentenceTransformer class.
            """
            module = gate_import(
                "sentence_transformers",
                "CodeRank embeddings (install `sentence-transformers`)",
            )
            sentence_transformer_cls = getattr(module, "SentenceTransformer", None)
            if sentence_transformer_cls is None:
                msg = "sentence_transformers does not expose SentenceTransformer"
                raise RuntimeError(msg)
            instance = sentence_transformer_cls(
                settings.model_id,
                trust_remote_code=settings.trust_remote_code,
                device=settings.device,
            )
            return cast("SentenceEncoderProtocol", instance)

        return cls(model_provider=_provider)


class CodeRankEmbedder:
    """Encode queries or code snippets with the CodeRank bi-encoder.

    This wrapper enforces the instruction prefix required by the CodeRankEmbed
    model card and caches the loaded ``SentenceTransformer`` per ``(model_id,
    device)`` tuple to avoid repeated initialization overhead.
    """

    _MODEL_CACHE: ClassVar[dict[tuple[str, str], SentenceEncoderProtocol]] = {}
    _CACHE_LOCK: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        *,
        settings: SupportsCodeRankSettings,
        context: CodeRankEmbedderContext | None = None,
    ) -> None:
        """Initialize CodeRank embedder.

        Parameters
        ----------
        settings : SupportsCodeRankSettings
            Settings containing model ID, device, and embedding configuration.
        context : CodeRankEmbedderContext | None, optional
            Optional context for dependency injection. If None, uses production context.
        """
        self.model_id = settings.model_id
        self.device = settings.device
        self.trust_remote_code = settings.trust_remote_code
        self.query_prefix = settings.query_prefix
        self.normalize = settings.normalize
        self.batch_size = settings.batch_size
        self._settings = settings
        self._context = context or CodeRankEmbedderContext.production()

    def encode_queries(self, queries: Iterable[str]) -> NDArrayF32:
        """Return CodeRank embeddings for queries with prefix applied.

        Parameters
        ----------
        queries : Iterable[str]
            Iterable of query strings. Each query will have the configured
            query_prefix prepended before encoding.

        Returns
        -------
        NDArrayF32
            Array of query embeddings with shape (num_queries, embedding_dim).

        Raises
        ------
        ValueError
            If queries is empty or contains no valid query strings.
        """
        query_list = [self.query_prefix + (q or "") for q in queries]
        if not query_list:
            msg = "encode_queries requires at least one query string."
            raise ValueError(msg)
        model = self._ensure_model()
        vectors = model.encode(
            query_list,
            normalize_embeddings=self.normalize,
            batch_size=self.batch_size,
        )
        return np.asarray(vectors, dtype=np.float32).reshape(len(query_list), -1)

    def encode_codes(self, snippets: Iterable[str]) -> NDArrayF32:
        """Return embeddings for code snippets (used during indexing).

        Parameters
        ----------
        snippets : Iterable[str]
            Iterable of code snippet strings to embed. Used during indexing
            to create document embeddings.

        Returns
        -------
        NDArrayF32
            Array of code embeddings with shape (num_snippets, embedding_dim).

        Raises
        ------
        ValueError
            If snippets is empty or contains no valid code snippets.
        """
        snippet_list = [snippet or "" for snippet in snippets]
        if not snippet_list:
            msg = "encode_codes requires at least one code snippet."
            raise ValueError(msg)
        model = self._ensure_model()
        vectors = model.encode(
            snippet_list,
            normalize_embeddings=self.normalize,
            batch_size=self.batch_size,
        )
        return np.asarray(vectors, dtype=np.float32).reshape(len(snippet_list), -1)

    def _ensure_model(self) -> SentenceEncoderProtocol:
        """Load the underlying SentenceTransformer lazily.

        Extended Summary
        ----------------
        Implements lazy loading and caching of the SentenceTransformer model instance.
        Uses a thread-safe cache keyed by model_id and device to avoid redundant model
        loads. This method is called internally before encoding operations.

        Returns
        -------
        SentenceEncoderProtocol
            Cached or newly loaded SentenceTransformer model instance conforming to
            the SentenceEncoderProtocol interface. The model is cached per (model_id, device)
            tuple for subsequent calls.

        Notes
        -----
        Thread-safe via module-level lock. Model loading is expensive (network I/O and
        GPU memory allocation), so caching is critical for performance. Cache entries
        persist for the lifetime of the process.
        """
        cache_key = (self.model_id, self.device)
        with self._CACHE_LOCK:
            cached = self._MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached
            model = self._context.model_provider(self._settings)
            self._MODEL_CACHE[cache_key] = model
            return model
