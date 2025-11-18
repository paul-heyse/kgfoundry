"""Narrow SPLADE engine hooking into Pyserini impact search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32

_sentence_transformers = LazyModule("sentence_transformers", "splade query encoder")
_lucene = LazyModule("pyserini.search.lucene", "splade impact searcher")


class SpladeBackend(Protocol):
    """Minimal surface that SPLADE engines rely on."""

    def encode_query(self, text: str) -> NDArrayF32:
        """Encode ``text`` into a SPLADE query representation."""

    def search(self, query_vec: NDArrayF32, k: int) -> Sequence[tuple[int, float]]:
        """Return ``(doc_id, score)`` pairs for an encoded query."""


@dataclass(frozen=True, slots=True)
class SPLADEEngine:
    """Narrow SPLADE engine that handles encode/search orchestration only."""

    backend: SpladeBackend

    def encode_query(self, text: str) -> NDArrayF32:
        return self.backend.encode_query(text)

    def search(self, query_text: str, *, k: int) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        query_vec = self.encode_query(query_text)
        hits = self.backend.search(query_vec, k)
        return [(int(doc_id), float(score)) for doc_id, score in hits][:k]

    def serialize_method(self) -> dict[str, object]:
        return {"channel": "splade", "impl": type(self.backend).__name__}


class SpladeImpactBackend(SpladeBackend):
    """SentenceTransformers + Pyserini impact backend used in production."""

    def __init__(
        self,
        *,
        model_dir: Path,
        onnx_dir: Path,
        onnx_file: str,
        provider: str,
        index_dir: Path,
        quantization: int,
        max_terms: int,
        max_query_terms: int,
        prune_below: float,
        static_prune_pct: float,
    ) -> None:
        if not index_dir.exists():
            msg = f"SPLADE impact index not found: {index_dir}"
            raise FileNotFoundError(msg)
        encoder_cls = _sentence_transformers.module().SparseEncoder
        model_kwargs: dict[str, object] = {"provider": provider}
        resolved_model_dir = model_dir
        resolved_onnx = onnx_dir / onnx_file
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
        self._searcher = _lucene.module().LuceneImpactSearcher(str(index_dir))
        self._quantization = int(quantization)
        self._max_terms = int(max_terms)
        self._max_query_terms = max(0, int(max_query_terms))
        self._prune_below = max(0.0, float(prune_below))
        self._static_prune_pct = min(max(0.0, float(static_prune_pct)), 1.0)

    def encode_query(self, text: str) -> NDArrayF32:
        return self._encoder.encode_query([text])

    def search(self, query_vec: NDArrayF32, k: int) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        decoded = self._encoder.decode(query_vec, top_k=None)
        if not decoded or not decoded[0]:
            return []
        filtered = self._filter_pairs(decoded[0])
        if not filtered:
            return []
        bow = self._build_bow(filtered)
        if not bow:
            return []
        try:
            hits = self._searcher.search(bow, k=k)
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
        filtered = [(token, weight) for token, weight in pairs if weight > 0]
        if self._prune_below > 0.0:
            filtered = [(token, weight) for token, weight in filtered if weight >= self._prune_below]
        if self._static_prune_pct > 0.0 and filtered:
            keep = max(1, round(len(filtered) * (1.0 - self._static_prune_pct)))
            filtered = sorted(filtered, key=lambda item: item[1], reverse=True)[:keep]
        if self._max_query_terms > 0:
            filtered = filtered[: self._max_query_terms]
        return filtered

    def _build_bow(self, pairs: Sequence[tuple[str, float]]) -> str:
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


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


__all__ = [
    "SPLADEEngine",
    "SpladeBackend",
    "SpladeImpactBackend",
]
