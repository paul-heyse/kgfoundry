"""Narrow SPLADE engine hooking into Pyserini impact search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32

_sentence_transformers = LazyModule("sentence_transformers", "splade query encoder")
_lucene = LazyModule("pyserini.search.lucene", "splade impact searcher")


SpladeQueryRepresentation = NDArrayF32 | str | Mapping[str, float]


class SpladeBackend(Protocol):
    """Minimal surface that SPLADE engines rely on."""

    def encode_query(self, text: str) -> SpladeQueryRepresentation:
        """Encode ``text`` into a SPLADE query representation."""
        ...

    def search(self, query_vec: SpladeQueryRepresentation, k: int) -> Sequence[tuple[int, float]]:
        """Return ``(doc_id, score)`` pairs for an encoded query."""
        ...


@dataclass(frozen=True, slots=True)
class SPLADEEngine:
    """Narrow SPLADE engine that handles encode/search orchestration only.

    Attributes
    ----------
    backend : SpladeBackend
        SPLADE backend implementation providing encoding and search capabilities.
    """

    backend: SpladeBackend

    def encode_query(self, text: str) -> SpladeQueryRepresentation:
        """Encode query text into SPLADE sparse vector representation.

        Parameters
        ----------
        text : str
            Query text to encode.

        Returns
        -------
        SpladeQueryRepresentation
            SPLADE sparse query vector or weighted string.
        """
        return self.backend.encode_query(text)

    def search(self, query_text: str, *, k: int) -> list[tuple[int, float]]:
        """Search SPLADE index for query text.

        Parameters
        ----------
        query_text : str
            Query string to search for.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) pairs, sorted by score descending.
        """
        if k <= 0:
            return []
        query_vec = self.encode_query(query_text)
        hits = self.backend.search(query_vec, k)
        return [(int(doc_id), float(score)) for doc_id, score in hits][:k]

    def serialize_method(self) -> dict[str, object]:
        """Serialize engine configuration for logging/debugging.

        Returns
        -------
        dict[str, object]
            Dictionary with channel name and backend implementation class name.
        """
        return {"channel": "splade", "impl": type(self.backend).__name__}


@dataclass(frozen=True, slots=True)
class SpladeImpactBackendConfig:
    """Configuration bundle for :class:`SpladeImpactBackend`.

    Attributes
    ----------
    model_dir : Path
        Directory path containing SPLADE PyTorch model files.
    onnx_dir : Path
        Directory path containing ONNX model files for SPLADE encoding.
    onnx_file : str
        Filename of the ONNX model file within onnx_dir.
    provider : str
        Device provider for SPLADE encoding (e.g., "cpu", "cuda").
    index_dir : Path
        Directory path containing the SPLADE Lucene impact index.
    quantization : int
        Quantization level for model weights (typically 100 for int8).
    max_terms : int
        Maximum number of terms in SPLADE representations. Must be positive.
    max_query_terms : int
        Maximum number of terms to extract from queries. Must be non-negative.
    prune_below : float
        Minimum token weight threshold for pruning SPLADE tokens. Tokens below
        this threshold are discarded. Must be non-negative.
    static_prune_pct : float
        Static pruning percentage for SPLADE tokens (0.0 to 1.0). Tokens are
        pruned based on this percentage before max_query_terms filtering.
    """

    model_dir: Path
    onnx_dir: Path
    onnx_file: str
    provider: str
    index_dir: Path
    quantization: int
    max_terms: int
    max_query_terms: int
    prune_below: float
    static_prune_pct: float


class SpladeImpactBackend(SpladeBackend):
    """SentenceTransformers + Pyserini impact backend used in production.

    Parameters
    ----------
    config : SpladeImpactBackendConfig
        Configuration bundle containing model paths, index directory,
        and encoding parameters.
    onnx_encoder : object | None, optional
        Optional ONNX encoder implementing ``encode`` or ``encode_to_impact``.

    Raises
    ------
    FileNotFoundError
        If the impact index directory does not exist.
    """

    def __init__(
        self,
        config: SpladeImpactBackendConfig,
        *,
        onnx_encoder: object | None = None,
    ) -> None:
        if not config.index_dir.exists():
            msg = f"SPLADE impact index not found: {config.index_dir}"
            raise FileNotFoundError(msg)
        self._external_encoder = onnx_encoder
        self._encoder = None
        if onnx_encoder is None:
            encoder_cls = _sentence_transformers.module().SparseEncoder
            model_kwargs: dict[str, object] = {"provider": config.provider}
            resolved_model_dir = config.model_dir
            resolved_onnx = config.onnx_dir / config.onnx_file
            if resolved_onnx.exists():
                try:
                    rel = resolved_onnx.relative_to(resolved_model_dir)
                    model_kwargs["file_name"] = str(rel)
                except ValueError:
                    model_kwargs["file_name"] = str(resolved_onnx)
            self._encoder = encoder_cls(
                str(resolved_model_dir),
                backend="onnx",
                model_kwargs=model_kwargs,
            )
        self._searcher = _lucene.module().LuceneImpactSearcher(str(config.index_dir))
        self._quantization = int(config.quantization)
        self._max_terms = int(config.max_terms)
        self._max_query_terms = max(0, int(config.max_query_terms))
        self._prune_below = max(0.0, float(config.prune_below))
        self._static_prune_pct = min(max(0.0, float(config.static_prune_pct)), 1.0)

    def encode_query(self, text: str) -> SpladeQueryRepresentation:
        """Encode query text into SPLADE sparse vector representation.

        Parameters
        ----------
        text : str
            Query text to encode.

        Returns
        -------
        SpladeQueryRepresentation
            SPLADE sparse query representation (vector or weighted string).

        Raises
        ------
        RuntimeError
            If the SPLADE encoder is unavailable.
        """
        external: Any = self._external_encoder
        if external is not None:
            if hasattr(external, "encode_to_impact"):
                return cast("Mapping[str, float]", external.encode_to_impact(text))
            if hasattr(external, "encode"):
                return cast("str", external.encode(text))
        if self._encoder is None:
            msg = "SPLADE encoder unavailable"
            raise RuntimeError(msg)
        return self._encoder.encode_query([text])

    def search(self, query_vec: SpladeQueryRepresentation, k: int) -> list[tuple[int, float]]:
        """Search SPLADE impact index with encoded query representation.

        Parameters
        ----------
        query_vec : SpladeQueryRepresentation
            Pre-encoded SPLADE query vector, weighted string, or mapping.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) pairs, sorted by score descending.

        Raises
        ------
        RuntimeError
            If the underlying Pyserini searcher fails.
        """
        if k <= 0:
            return []
        weighted = self._coerce_weighted_input(query_vec)
        if not weighted:
            return []
        try:
            hits = self._searcher.search(weighted, k=k)
        except Exception as exc:  # pragma: no cover - Pyserini raises
            msg = "SPLADE search failed"
            raise RuntimeError(msg) from exc
        results: list[tuple[int, float]] = []
        for hit in hits:
            doc_id = _safe_int(hit.docid)
            if doc_id is None:
                continue
            results.append((doc_id, float(hit.score)))
        return results

    def _filter_pairs(self, pairs: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
        """Filter and prune SPLADE token-weight pairs based on configuration thresholds.

        Parameters
        ----------
        pairs : Sequence[tuple[str, float]]
            Sequence of (token, weight) pairs from SPLADE encoding.

        Returns
        -------
        list[tuple[str, float]]
            Filtered list of (token, weight) pairs after applying pruning thresholds:
            - Removes pairs with weight <= 0
            - Removes pairs below prune_below threshold (if configured)
            - Applies static pruning percentage (if configured)
            - Limits to max_query_terms (if configured)
        """
        filtered = [(token, weight) for token, weight in pairs if weight > 0]
        if self._prune_below > 0.0:
            filtered = [
                (token, weight) for token, weight in filtered if weight >= self._prune_below
            ]
        if self._static_prune_pct > 0.0 and filtered:
            keep = max(1, round(len(filtered) * (1.0 - self._static_prune_pct)))
            filtered = sorted(filtered, key=lambda item: item[1], reverse=True)[:keep]
        if self._max_query_terms > 0:
            filtered = filtered[: self._max_query_terms]
        return filtered

    def _build_bow(self, pairs: Sequence[tuple[str, float]]) -> str:
        """Build bag-of-words query string from filtered token-weight pairs.

        Parameters
        ----------
        pairs : Sequence[tuple[str, float]]
            Sequence of (token, weight) pairs, typically already filtered.

        Returns
        -------
        str
            Space-separated bag-of-words query string where each token appears
            a number of times proportional to its quantized weight. The number
            of repetitions is limited by quantization level and remaining term budget.
        """
        tokens: list[str] = []
        query_cap = self._max_query_terms or self._max_terms
        remaining = min(self._max_terms, query_cap) if query_cap else self._max_terms
        for token, weight in pairs:
            if weight <= 0 or remaining <= 0:
                continue
            impact = round(weight * self._quantization)
            if impact <= 0:
                continue
            repetitions = min(impact, remaining)
            tokens.extend([token] * repetitions)
            remaining -= repetitions
            if remaining <= 0:
                break
        return " ".join(tokens)

    def _coerce_weighted_input(self, value: SpladeQueryRepresentation) -> str:
        """Convert SPLADE query representation to weighted query string.

        Parameters
        ----------
        value : SpladeQueryRepresentation
            Query representation in one of three formats:
            - str: Already a weighted query string (returned as-is)
            - Mapping[str, float]: Token-weight mapping (converted to weighted string)
            - NDArrayF32: SPLADE vector (decoded and converted to weighted string)

        Returns
        -------
        str
            Weighted query string suitable for Pyserini impact search. Returns
            empty string if value cannot be converted or encoder is unavailable.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            return self._mapping_to_weighted(value)
        if self._encoder is None:
            return ""
        decoded = self._encoder.decode(value, top_k=None)
        if not decoded or not decoded[0]:
            return ""
        filtered = self._filter_pairs(decoded[0])
        if not filtered:
            return ""
        return self._build_bow(filtered)

    @staticmethod
    def _mapping_to_weighted(values: Mapping[str, float]) -> str:
        """Convert token-weight mapping to Pyserini weighted query format.

        Parameters
        ----------
        values : Mapping[str, float]
            Dictionary mapping tokens to their weights.

        Returns
        -------
        str
            Space-separated weighted query string in format "token^weight",
            where tokens with weight <= 0 are excluded.
        """
        parts: list[str] = []
        for token, weight in values.items():
            impact = float(weight)
            if impact <= 0:
                continue
            parts.append(f"{token}^{impact:.6f}")
        return " ".join(parts)


def _safe_int(value: object) -> int | None:
    """Convert a value to an integer, returning None on failure.

    Parameters
    ----------
    value : object
        Value to convert to integer. Can be any type that can be converted
        via str() and then int().

    Returns
    -------
    int | None
        The integer representation of the value, or None if conversion fails
        due to TypeError or ValueError.
    """
    try:
        return int(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


__all__ = [
    "SPLADEEngine",
    "SpladeBackend",
    "SpladeImpactBackend",
    "SpladeImpactBackendConfig",
    "SpladeQueryRepresentation",
]
