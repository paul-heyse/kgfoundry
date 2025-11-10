"""Token-level XTR index manager with late-interaction scoring utilities."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, cast

import numpy as np

from codeintel_rev.config.settings import XTRConfig
from kgfoundry_common.logging import get_logger
from kgfoundry_common.typing import gate_import

LOGGER = get_logger(__name__)


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

    __slots__ = ("device", "meta", "model", "tokenizer", "tokens")

    def __init__(self) -> None:
        self.meta: XTRMetadata | None = None
        self.tokens: np.memmap | None = None
        self.tokenizer: Any | None = None
        self.model: Any | None = None
        self.device: str | None = None


@dataclass(slots=True, frozen=True)
class XTRIndex:
    """Memory-mapped XTR token index with query encoding + scoring helpers."""

    root: Path
    config: XTRConfig
    _runtime: _XTRIndexRuntime = field(default_factory=_XTRIndexRuntime, init=False, repr=False)

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
            LOGGER.debug(
                "xtr_artifacts_missing",
                extra={
                    "meta_path": str(meta_path),
                    "token_path": str(token_path),
                },
            )
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
            LOGGER.exception(
                "xtr_memmap_failed",
                extra={"token_path": str(token_path), "error": str(exc)},
            )
            raise
        state = self._runtime
        state.meta = meta
        state.tokens = tokens
        LOGGER.info(
            "xtr_index_opened",
            extra={
                "root": str(self.root),
                "dim": meta["dim"],
                "tokens": meta["total_tokens"],
                "chunks": meta["doc_count"],
                "dtype": meta["dtype"],
            },
        )

    @property
    def ready(self) -> bool:
        """Return ``True`` when both metadata and token memmap are available.

        Returns
        -------
        bool
            ``True`` if the index is ready for scoring.
        """
        state = self._runtime
        return state.meta is not None and state.tokens is not None

    def metadata(self) -> XTRMetadata | None:
        """Return a shallow copy of index metadata when loaded.

        Returns
        -------
        XTRMetadata | None
            Metadata dictionary or ``None`` when index not opened.
        """
        state = self._runtime
        if state.meta is None:
            return None
        return cast("XTRMetadata", dict(state.meta))

    def encode_query_tokens(self, text: str) -> np.ndarray:
        """Encode text into normalized token embeddings.

        Parameters
        ----------
        text : str
            Query text string to encode. Will be tokenized and truncated to
            max_query_tokens if necessary.

        Returns
        -------
        np.ndarray
            Array shaped [tokens, dim] with L2-normalized token vectors.
            Each row is a token embedding normalized to unit length.
        """
        tokenizer, model = self._ensure_encoder()
        torch_module = gate_import("torch", "XTR query encoding")
        device = self._resolve_device(cast("TorchDeviceModule", torch_module))
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
            LOGGER.warning(
                "XTR encoder dimension mismatch",
                extra={
                    "expected": self.config.dim,
                    "observed": result.shape[1],
                    "model_id": self.config.model_id,
                },
            )
        return result

    def search(
        self,
        query: str,
        k: int,
        *,
        explain: bool = False,
        topk_explanations: int = 5,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        """
        Perform index-wide MaxSim search (wide mode).

        Returns
        -------
        list[tuple[int, float, dict[str, Any] | None]]
            Ranked list of chunk identifiers, scores, and optional explanations.
        """
        if not self.ready or k <= 0:
            return []
        state = self._runtime
        meta = state.meta
        if meta is None:
            return []
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
        """
        Rescore a Stage-0 candidate set (narrow mode).

        Returns
        -------
        list[tuple[int, float, dict[str, Any] | None]]
            Ranked list restricted to the provided candidate chunk identifiers.
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
        query_vecs: np.ndarray,
        candidate_chunk_ids: Iterable[int],
        *,
        explain: bool = False,
        topk_explanations: int = 5,
        limit: int | None = None,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        """Compute MaxSim scores for candidate chunk IDs.

        Parameters
        ----------
        query_vecs : np.ndarray
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
            LOGGER.debug("xtr_not_ready", extra={"root": str(self.root)})
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

    def _ensure_encoder(self) -> tuple[Any, Any]:
        """Instantiate and cache tokenizer/model pair.

        Returns
        -------
        tuple[Any, Any]
            Tokenizer/model pair loaded from Hugging Face.
        """
        state = self._runtime
        if state.tokenizer is not None and state.model is not None:
            return state.tokenizer, state.model
        transformers = cast("Any", gate_import("transformers", "XTR encoder loading"))
        auto_tokenizer_cls = transformers.AutoTokenizer
        auto_model_cls = transformers.AutoModel
        tokenizer = auto_tokenizer_cls.from_pretrained(self.config.model_id)
        model = auto_model_cls.from_pretrained(self.config.model_id)
        torch_module = cast("TorchDeviceModule", gate_import("torch", "XTR encoder device"))
        device = self._resolve_device(torch_module)
        model.to(device)
        model.eval()
        state.tokenizer = tokenizer
        state.model = model
        return tokenizer, model

    def _resolve_device(self, torch_module: TorchDeviceModule) -> object:
        """Resolve the runtime torch.device honoring config preferences.

        Parameters
        ----------
        torch_module : TorchDeviceModule
            Torch module instance used to check CUDA availability and create
            device objects.

        Returns
        -------
        object
            Device reference (torch.device) pointing to cpu or cuda based on
            config and availability.
        """
        state = self._runtime
        configured = self.config.device or "cpu"
        if configured == "cuda" and not torch_module.cuda.is_available():
            if state.device != "cpu":
                LOGGER.warning(
                    "XTR requested CUDA but it is unavailable; falling back to CPU.",
                )
            state.device = "cpu"
        else:
            state.device = configured
        return torch_module.device(state.device)

    def _slice_chunk(self, chunk_id: int) -> np.ndarray:
        """Return token matrix slice for chunk_id.

        Parameters
        ----------
        chunk_id : int
            Chunk ID to extract embeddings for. Must exist in the index metadata.

        Returns
        -------
        np.ndarray
            View over the token matrix for the requested chunk. Array shaped
            [tokens, dim] with token embeddings.

        Raises
        ------
        RuntimeError
            If the index has not been opened.
        KeyError
            If the chunk identifier is not present in metadata.
        """
        state = self._runtime
        meta = state.meta
        tokens = state.tokens
        if meta is None or tokens is None:
            msg = f"XTR index not ready when slicing chunk {chunk_id}"
            raise RuntimeError(msg)
        try:
            idx = meta["chunk_ids"].index(chunk_id)
        except ValueError as exc:
            raise KeyError(chunk_id) from exc
        offset = meta["offsets"][idx]
        length = meta["lengths"][idx]
        return np.asarray(tokens[offset : offset + length])


class TorchDeviceModule(Protocol):
    """Subset of torch API required for device resolution."""

    class _CudaAPI(Protocol):
        def is_available(self) -> bool: ...

    cuda: _CudaAPI

    def device(self, name: str) -> object:
        """Return a torch.device handle."""
        ...
