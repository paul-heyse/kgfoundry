"""Token-level XTR index manager with late-interaction scoring utilities."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.config.api import XTRSettings
from codeintel_rev.runtime import RuntimeCell
from codeintel_rev.runtime.imports import gate_import
from codeintel_rev.typing import NDArrayF32, TorchModule

if TYPE_CHECKING:
    import numpy as np

    from codeintel_rev.config.settings import XTRConfig as LegacyXTRConfig
else:
    np = cast("np", LazyModule("numpy", "XTR index operations"))
    LegacyXTRConfig = object


class XTRMetadata(TypedDict):
    """Metadata persisted alongside the token memmap."""

    dim: int
    dtype: Literal["float16", "float32"]
    total_tokens: int
    doc_count: int
    chunk_ids: list[int]
    offsets: list[int]
    lengths: list[int]


class _XTRIndexRuntime:
    """Mutable runtime artifacts for XTRIndex."""

    __slots__ = (
        "chunk_lookup",
        "device",
        "meta",
        "model",
        "test_vectors",
        "tokenizer",
        "tokens",
    )

    def __init__(self) -> None:
        """Initialize XTR index runtime state.

        Creates a new runtime state tracker with all fields set to None.
        Fields are populated during index loading and must be cleaned up
        via the close() method to release resources.
        """
        self.meta: XTRMetadata | None = None
        self.tokens: np.memmap | None = None
        self.tokenizer: Any | None = None
        self.model: Any | None = None
        self.device: str | None = None
        self.chunk_lookup: dict[int, tuple[int, int]] | None = None
        self.test_vectors: NDArrayF32 | None = None

    def close(self) -> None:
        """Release loaded tokenizer/model/memmaps."""
        self.meta = None
        self.tokens = None
        self.tokenizer = None
        self.model = None
        self.device = None
        self.chunk_lookup = None
        self.test_vectors = None


def _coerce_xtr_settings(config: XTRSettings | LegacyXTRConfig) -> XTRSettings:
    """Return XTRSettings from either dataclass or legacy struct.

    Parameters
    ----------
    config : XTRSettings | object
        Candidate configuration object that may already be ``XTRSettings`` or
        a msgspec struct from :mod:`codeintel_rev.config.settings`.

    Returns
    -------
    XTRSettings
        Normalized dataclass representation of the supplied configuration.
    """
    if isinstance(config, XTRSettings):
        return config
    dtype_value = str(getattr(config, "dtype", "float16")).lower()
    dtype: Literal["float16", "float32"] = "float32" if dtype_value == "float32" else "float16"
    mode_value = str(getattr(config, "mode", "narrow")).lower()
    mode: Literal["narrow", "wide"] = "wide" if mode_value == "wide" else "narrow"
    return XTRSettings(
        model_id=getattr(config, "model_id", "nomic-ai/CodeRankEmbed"),
        device=getattr(config, "device", "cuda"),
        max_query_tokens=int(getattr(config, "max_query_tokens", 256)),
        candidate_k=int(getattr(config, "candidate_k", 200)),
        dim=int(getattr(config, "dim", 768)),
        dtype=dtype,
        enable=bool(getattr(config, "enable", False)),
        mode=mode,
    )


@dataclass(slots=True, frozen=True)
class XTRIndex:
    """Memory-mapped XTR token index with query encoding + scoring helpers.

    Attributes
    ----------
    root : Path
        Root directory path containing XTR index files (token embeddings,
        metadata JSON).
    config : XTRSettings | LegacyXTRConfig
        XTR configuration settings. Normalized to XTRSettings in __post_init__.
    """

    root: Path
    config: XTRSettings | LegacyXTRConfig
    _cell: RuntimeCell[_XTRIndexRuntime] = field(
        default_factory=lambda: RuntimeCell(name="xtr-index"),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Normalize config to AppConfig dataclass."""
        normalized = _coerce_xtr_settings(self.config)
        object.__setattr__(self, "config", normalized)

    def seed_runtime_for_tests(self, encoder_vectors: NDArrayF32 | None = None) -> None:
        """Seed runtime state with explicit encoder vectors for testing."""
        state = self._runtime()
        state.test_vectors = encoder_vectors

    def open(self) -> None:
        """Open metadata and memory-map the token matrix if artifacts exist.

        Raises
        ------
        ValueError
            If the stored metadata does not match the token matrix shape.
        """
        meta_path = self.root / "index.meta.json"
        token_name = "tokens.f32" if self.config.dtype == "float32" else "tokens.f16"
        token_path = self.root / token_name

        if not meta_path.exists() or not token_path.exists():
            return

        with meta_path.open("r", encoding="utf-8") as handle:
            meta: XTRMetadata = json.load(handle)
        dtype = np.float32 if meta["dtype"] == "float32" else np.float16
        try:
            tokens = np.memmap(
                token_path,
                dtype=dtype,
                mode="r",
                shape=(meta["total_tokens"], meta["dim"]),
            )
        except ValueError as exc:
            message = f"Token matrix shape mismatch for {token_path}"
            raise ValueError(message) from exc
        state = self._ensure_state()
        state.close()
        state.meta = meta
        state.tokens = tokens
        state.chunk_lookup = self._build_chunk_lookup(meta)

    @property
    def ready(self) -> bool:
        """Return ``True`` when both metadata and token memmap are available.

        Returns
        -------
        bool
            ``True`` if the index is ready for scoring.
        """
        state = self._current_state()
        return bool(state and state.meta is not None and state.tokens is not None)

    def metadata(self) -> XTRMetadata | None:
        """Return a shallow copy of index metadata when loaded.

        Returns
        -------
        XTRMetadata | None
            Metadata dictionary or ``None`` when index not opened.
        """
        state = self._current_state()
        if state is None or state.meta is None:
            return None
        return cast("XTRMetadata", dict(state.meta))

    def encode_query_tokens(self, text: str) -> NDArrayF32:
        """Encode text into normalized token embeddings.

        Parameters
        ----------
        text : str
            Query text string to encode. Will be tokenized and truncated to
            max_query_tokens if necessary.

        Returns
        -------
        NDArrayF32
            Array shaped [tokens, dim] with L2-normalized token vectors.
            Each row is a token embedding normalized to unit length.
        """
        state = self._runtime()
        if state.test_vectors is not None:
            return state.test_vectors
        tokenizer, model = self._ensure_encoder()
        torch_module = gate_import("torch", "XTR query encoding")
        device = self._resolve_device(cast("TorchModule", torch_module))
        torch_any = cast("Any", torch_module)
        with torch_any.inference_mode():
            inputs = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=self.config.max_query_tokens,
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            outputs = model(**inputs)
            hidden = outputs.last_hidden_state  # [1, T, D]
            vecs = torch_any.nn.functional.normalize(hidden[0], dim=-1)
            result = vecs.detach().cpu().to(torch_any.float32).numpy()
        if result.shape[1] != self.config.dim:
            pass
        return result

    def search(
        self,
        query: str,
        k: int,
        *,
        explain: bool = False,
        topk_explanations: int = 5,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        """Perform index-wide MaxSim search across all chunks (wide mode).

        Extended Summary
        ----------------
        This method performs exhaustive MaxSim search across the entire XTR index,
        scoring all chunks against the query and returning the top-k results. It is
        used for wide-mode retrieval when no initial candidate set is available. The
        method encodes the query into token embeddings, computes MaxSim scores against
        all document chunks, and returns ranked results with optional explainability
        data. This is the primary entry point for XTR-based search when operating
        without a Stage-0 retrieval system.

        Parameters
        ----------
        query : str
            Natural language search query string. Will be tokenized and encoded
            into query token embeddings for MaxSim computation.
        k : int
            Maximum number of results to return. Must be positive. Results are
            ranked by MaxSim score in descending order.
        explain : bool, optional
            If True, include explainability payload with token-level alignment
            information for each result. Defaults to False.
        topk_explanations : int, optional
            Maximum number of token matches to include in explainability payload
            when explain=True. Defaults to 5.

        Returns
        -------
        list[tuple[int, float, dict[str, Any] | None]]
            Ranked list of (chunk_id, score, explainability_payload) tuples.
            Scores are MaxSim sums across query tokens. Explainability payload is
            None if explain=False or no matches found. Length is min(k, total_chunks).

        Notes
        -----
        Time complexity O(n * m * d) where n is query tokens, m is total document
        tokens across all chunks, and d is embedding dimension. Space complexity
        O(n * d + m * d) for query and document embeddings. The method performs
        I/O to read token embeddings from memory-mapped files. Thread-safe if
        index is read-only. Returns empty list if index is not ready or k <= 0.

        Examples
        --------
        >>> # Requires XTRIndex instance with opened index
        >>> # index = XTRIndex(root=Path("..."), config=...)
        >>> # index.open()
        >>> # results = index.search("vector store", k=10)
        >>> # len(results) <= 10
        >>> # all(isinstance(r[0], int) and isinstance(r[1], float) for r in results)
        >>> # True
        """
        if not self.ready or k <= 0:
            return []
        state = self._current_state()
        if state is None or state.meta is None:
            return []
        meta = state.meta
        query_vecs = self.encode_query_tokens(query)
        candidates = meta["chunk_ids"]
        return self.score_candidates(
            query_vecs,
            candidates,
            explain=explain,
            topk_explanations=topk_explanations,
            limit=k,
        )

    def rescore(
        self,
        query: str,
        candidate_chunk_ids: Iterable[int],
        *,
        explain: bool = False,
        topk_explanations: int = 5,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        """Rescore a Stage-0 candidate set using MaxSim (narrow mode).

        Extended Summary
        ----------------
        This method performs focused MaxSim rescoring on a pre-filtered set of
        candidate chunks, typically from an initial retrieval stage (e.g., CodeRank
        FAISS search). It encodes the query, computes MaxSim scores only for the
        provided candidates, and returns ranked results. This narrow-mode operation
        is more efficient than full index search when a high-quality candidate set
        is available. The method is used in two-stage retrieval pipelines where
        Stage-0 provides candidates and XTR provides late-interaction reranking.

        Parameters
        ----------
        query : str
            Natural language search query string. Will be tokenized and encoded
            into query token embeddings for MaxSim computation.
        candidate_chunk_ids : Iterable[int]
            Iterable of chunk IDs from Stage-0 retrieval to rescore. Duplicates
            are automatically deduplicated. Empty iterables result in empty results.
        explain : bool, optional
            If True, include explainability payload with token-level alignment
            information for each result. Defaults to False.
        topk_explanations : int, optional
            Maximum number of token matches to include in explainability payload
            when explain=True. Defaults to 5.

        Returns
        -------
        list[tuple[int, float, dict[str, Any] | None]]
            Ranked list of (chunk_id, score, explainability_payload) tuples,
            restricted to the provided candidate chunk IDs. Scores are MaxSim sums
            across query tokens. Explainability payload is None if explain=False
            or no matches found. Results are sorted by score descending.

        Notes
        -----
        Time complexity O(n * m * d) where n is query tokens, m is total document
        tokens across candidate chunks, and d is embedding dimension. Space complexity
        O(n * d + c * m * d) where c is candidate count. More efficient than search()
        when candidate set is small relative to total chunks. The method performs
        I/O to read token embeddings from memory-mapped files. Thread-safe if index
        is read-only. Returns empty list if index is not ready or candidates is empty.

        Examples
        --------
        >>> # Requires XTRIndex instance with opened index
        >>> # index = XTRIndex(root=Path("..."), config=...)
        >>> # index.open()
        >>> # candidates = [1, 2, 3, 4, 5]
        >>> # results = index.rescore("vector store", candidates, explain=True)
        >>> # len(results) <= len(candidates)
        >>> # all(r[0] in candidates for r in results)
        >>> # True
        """
        materialized = [int(cid) for cid in candidate_chunk_ids]
        if not materialized or not self.ready:
            return []
        query_vecs = self.encode_query_tokens(query)
        return self.score_candidates(
            query_vecs,
            materialized,
            explain=explain,
            topk_explanations=topk_explanations,
        )

    def score_candidates(
        self,
        query_vecs: NDArrayF32,
        candidate_chunk_ids: Iterable[int],
        *,
        explain: bool = False,
        topk_explanations: int = 5,
        limit: int | None = None,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        """Compute MaxSim scores for candidate chunk IDs.

        Parameters
        ----------
        query_vecs : NDArrayF32
            Query token embeddings array shaped [query_tokens, dim]. Used to compute
            MaxSim scores against document token embeddings.
        candidate_chunk_ids : Iterable[int]
            Iterable of chunk IDs to score. Duplicates are automatically deduplicated.
        explain : bool, optional
            If True, include explainability payload with token-level alignments.
            Defaults to False.
        topk_explanations : int, optional
            Maximum number of token matches to include in explainability payload.
            Defaults to 5.
        limit : int | None, optional
            Optional cap on the number of rescored results returned. ``None`` retains
            every candidate.

        Returns
        -------
        list[tuple[int, float, dict[str, Any] | None]]
            Ranked list containing (chunk_id, score, explainability_payload) tuples.
            Scores are MaxSim sums across query tokens. Explainability payload is None
            if explain=False or no matches found.
        """
        if not self.ready:
            return []

        query_array = np.asarray(query_vecs, dtype=np.float32)
        topk = max(1, topk_explanations)
        seen: set[int] = set()
        results: list[tuple[int, float, dict[str, Any] | None]] = []
        for chunk_id in candidate_chunk_ids:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            try:
                doc_vecs = self._slice_chunk(chunk_id)
            except KeyError:
                continue
            doc_array = np.asarray(doc_vecs, dtype=np.float32)
            if doc_array.size == 0:
                continue
            sims = query_array @ doc_array.T
            max_per_query = sims.max(axis=1)
            argmax = sims.argmax(axis=1)
            score = float(max_per_query.sum())
            payload = None
            if explain and max_per_query.size:
                explain_limit = min(topk, max_per_query.size)
                top_idx = np.argpartition(-max_per_query, explain_limit - 1)[:explain_limit]
                top_idx = top_idx[np.argsort(-max_per_query[top_idx])]
                payload = {
                    "token_matches": [
                        {
                            "q_index": int(idx),
                            "doc_index": int(argmax[idx]),
                            "similarity": float(max_per_query[idx]),
                        }
                        for idx in top_idx
                    ]
                }
            results.append((chunk_id, score, payload))

        results.sort(key=lambda item: item[1], reverse=True)
        if limit is not None and limit > 0:
            return results[:limit]
        return results

    @staticmethod
    def _initialize_runtime() -> _XTRIndexRuntime:
        """Create an empty runtime container.

        Returns
        -------
        _XTRIndexRuntime
            Fresh runtime container for the index.
        """
        return _XTRIndexRuntime()

    def _runtime(self) -> _XTRIndexRuntime:
        """Return the cached runtime structure, initializing if necessary.

        Returns
        -------
        _XTRIndexRuntime
            Runtime state managed by the internal RuntimeCell.
        """
        return self._cell.get_or_initialize(self._initialize_runtime)

    def _ensure_encoder(self) -> tuple[Any, Any]:
        """Instantiate and cache tokenizer/model pair.

        Returns
        -------
        tuple[Any, Any]
            Tokenizer/model pair loaded from Hugging Face.
        """
        state = self._ensure_state()
        if state.tokenizer is not None and state.model is not None:
            return state.tokenizer, state.model
        transformers = cast("Any", gate_import("transformers", "XTR encoder loading"))
        auto_tokenizer_cls = transformers.AutoTokenizer
        auto_model_cls = transformers.AutoModel
        tokenizer = auto_tokenizer_cls.from_pretrained(self.config.model_id)
        model = auto_model_cls.from_pretrained(self.config.model_id)
        torch_module = cast("TorchModule", gate_import("torch", "XTR encoder device"))
        device = self._resolve_device(torch_module)
        model.to(device)
        model.eval()
        state.tokenizer = tokenizer
        state.model = model
        return tokenizer, model

    def _resolve_device(self, torch_module: TorchModule) -> object:
        """Resolve the runtime torch.device honoring config preferences.

        Parameters
        ----------
        torch_module : TorchModule
            Torch module instance used to check CUDA availability and create
            device objects.

        Returns
        -------
        object
            Device reference (torch.device) pointing to cpu or cuda based on
            config and availability.
        """
        state = self._ensure_state()
        configured = (self.config.device or "cpu").strip()
        if configured.lower().startswith("cuda"):
            if not torch_module.cuda.is_available():
                state.device = "cpu"
                return torch_module.device(state.device)

            ordinal = self._parse_cuda_ordinal(configured)
            if ":" in configured and ordinal is None:
                state.device = "cpu"
                return torch_module.device(state.device)

            device_count = torch_module.cuda.device_count()
            if ordinal is not None:
                if device_count == 0:
                    state.device = "cpu"
                    return torch_module.device(state.device)
                if ordinal >= device_count:
                    selected = max(device_count - 1, 0)
                    state.device = f"cuda:{selected}"
                else:
                    state.device = f"cuda:{ordinal}"
                return torch_module.device(state.device)
            state.device = "cuda"
            return torch_module.device(state.device)

        state.device = configured
        return torch_module.device(state.device)

    @staticmethod
    def _parse_cuda_ordinal(value: str) -> int | None:
        """Extract CUDA device ordinal from a device string.

        Extended Summary
        ----------------
        This method parses a CUDA device string (e.g., "cuda:0", "cuda:1") to extract
        the device ordinal. It handles malformed input gracefully by returning None
        when the format is invalid or when no ordinal is specified. This is used
        internally by the XTR index to resolve device assignments from configuration
        strings and ensure proper device selection for tensor operations on hosts that
        still expose CUDA devices.

        Parameters
        ----------
        value : str
            Device string that may contain a CUDA ordinal in the format "cuda:<ordinal>".
            If the string doesn't contain a colon or the part after the colon is not
            a valid integer, the function returns None.

        Returns
        -------
        int | None
            Parsed ordinal as an integer (e.g., 0, 1, 2) when ``value`` contains
            ``cuda:<ordinal>``, or ``None`` when unspecified, invalid, or not in
            the expected format.

        Notes
        -----
        Time complexity O(1) - simple string split and int conversion. Space
        complexity O(1). No I/O or side effects. Handles ValueError exceptions
        from int() conversion by returning None, making it safe for malformed input.
        """
        parts = value.split(":", 1)
        if len(parts) == 1:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def _slice_chunk(self, chunk_id: int) -> NDArrayF32:
        """Return token matrix slice for chunk_id.

        Parameters
        ----------
        chunk_id : int
            Chunk ID to extract embeddings for. Must exist in the index metadata.

        Returns
        -------
        NDArrayF32
            View over the token matrix for the requested chunk. Array shaped
            [tokens, dim] with token embeddings.

        Raises
        ------
        RuntimeError
            If the index has not been opened.
        KeyError
            If the chunk identifier is not present in metadata.
        """
        state = self._current_state()
        if state is None or state.meta is None or state.tokens is None:
            msg = f"XTR index not ready when slicing chunk {chunk_id}"
            raise RuntimeError(msg)
        meta = state.meta
        tokens = state.tokens
        lookup = state.chunk_lookup
        if lookup is None:
            lookup = self._build_chunk_lookup(meta)
            state.chunk_lookup = lookup
        try:
            offset, length = lookup[chunk_id]
        except KeyError as exc:
            raise KeyError(chunk_id) from exc
        return np.asarray(tokens[offset : offset + length])

    @staticmethod
    def _build_chunk_lookup(meta: XTRMetadata) -> dict[int, tuple[int, int]]:
        """Build fast chunk metadata for offset lookups.

        Parameters
        ----------
        meta : XTRMetadata
            Metadata containing chunk dimensions for the index.

        Returns
        -------
        dict[int, tuple[int, int]]
            Mapping from chunk ID to (offset, length).
        """
        return {
            int(chunk_id): (int(offset), int(length))
            for chunk_id, offset, length in zip(
                meta["chunk_ids"],
                meta["offsets"],
                meta["lengths"],
                strict=True,
            )
        }

    def close(self) -> None:
        """Release runtime resources such as memmaps and tokenizer."""
        self._cell.close()

    def _ensure_state(self) -> _XTRIndexRuntime:
        """Ensure runtime state is initialized, creating if needed.

        Returns
        -------
        _XTRIndexRuntime
            Runtime state instance (newly created or existing).
        """
        return self._cell.get_or_initialize(_XTRIndexRuntime)

    def _current_state(self) -> _XTRIndexRuntime | None:
        """Get current runtime state without initializing.

        Returns
        -------
        _XTRIndexRuntime | None
            Current runtime state if initialized, None otherwise.
        """
        return self._cell.peek()
