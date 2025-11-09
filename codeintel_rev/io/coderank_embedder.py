"""Pooled wrapper around the CodeRank embedding SentenceTransformer."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, cast

import numpy as np

from kgfoundry_common.logging import get_logger
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

LOGGER = get_logger(__name__)


class CodeRankEmbedder:
    """Encode queries or code snippets with the CodeRank bi-encoder.

    This wrapper enforces the instruction prefix required by the CodeRankEmbed
    model card and caches the loaded ``SentenceTransformer`` per ``(model_id,
    device)`` tuple to avoid repeated initialization overhead.
    """

    _MODEL_CACHE: ClassVar[dict[tuple[str, str], SentenceTransformer]] = {}
    _CACHE_LOCK: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        *,
        model_id: str,
        device: str,
        trust_remote_code: bool,
        query_prefix: str,
        normalize: bool,
        batch_size: int,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.trust_remote_code = trust_remote_code
        self.query_prefix = query_prefix
        self.normalize = normalize
        self.batch_size = batch_size

    def encode_queries(self, queries: Iterable[str]) -> np.ndarray:
        """Return CodeRank embeddings for ``queries`` with prefix applied.

        Returns
        -------
        np.ndarray
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

    def encode_codes(self, snippets: Iterable[str]) -> np.ndarray:
        """Return embeddings for code snippets (used during indexing).

        Returns
        -------
        np.ndarray
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

    def _ensure_model(self) -> SentenceTransformer:
        """Load the underlying SentenceTransformer lazily.

        Returns
        -------
        SentenceTransformer
            Cached or newly loaded SentenceTransformer model instance.

        Raises
        ------
        RuntimeError
            If model loading fails or the model cannot be initialized.
        """
        cache_key = (self.model_id, self.device)
        with self._CACHE_LOCK:
            cached = self._MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached
            module = gate_import(
                "sentence_transformers",
                "CodeRank embeddings (install `sentence-transformers`)",
            )
            sentence_transformer_cls = getattr(module, "SentenceTransformer", None)
            if sentence_transformer_cls is None:
                msg = "sentence_transformers does not expose SentenceTransformer"
                raise RuntimeError(msg)
            model = sentence_transformer_cls(  # type: ignore[call-arg]
                self.model_id,
                trust_remote_code=self.trust_remote_code,
                device=self.device,
            )
            LOGGER.info(
                "Loaded CodeRank model",
                extra={"model_id": self.model_id, "device": self.device},
            )
            self._MODEL_CACHE[cache_key] = cast("SentenceTransformer", model)
            return cast("SentenceTransformer", model)
