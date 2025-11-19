"""Codemod that rewrites ``io/hybrid_search.py`` to the canonical coordinator."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import libcst as cst
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand

_COORDINATOR = dedent(
    """
    \"\"\"Thin Stage-0 hybrid search coordinator.\"\"\"

    from __future__ import annotations

    from collections.abc import Mapping, Sequence
    from dataclasses import dataclass, field

    from codeintel_rev.io.bm25_engine import BM25Engine
    from codeintel_rev.io.splade_engine import SPLADEEngine
    from codeintel_rev.retrieval.fusion.api import (
        FusionInput,
        FusionOptions,
        FusionProtocol,
        RRFWeighter,
    )
    from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult


    @dataclass(frozen=True, slots=True)
    class HybridSearchOptions:
        \"\"\"Coordinator options expressed in terms of channel budgets and fusion weights.\"\"\"

        weights: Mapping[str, float] | None = None
        per_channel_k: int = 100
        fusion_k: int = 50
        rrf_base: int = 60


    @dataclass(slots=True)
    class HybridSearchEngine:
        \"\"\"Stage-0 coordinator that delegates to BM25/SPLADE engines and fuses the results.\"\"\"

        bm25: BM25Engine
        splade: SPLADEEngine
        fusion: FusionProtocol | None = field(default=None, repr=False)

        def __post_init__(self) -> None:
            if self.fusion is None:
                self.fusion = RRFWeighter()

        def search(
            self,
            *,
            query: str,
            semantic_hits: Sequence[tuple[int, float]] | None,
            limit: int,
            options: HybridSearchOptions | None = None,
        ) -> HybridSearchResult:
            opts = options or HybridSearchOptions()
            fusion_limit = max(1, min(int(opts.fusion_k), int(limit)))
            per_channel_k = max(fusion_limit, int(opts.per_channel_k))
            warnings: list[str] = []

            bm25_pairs, bm25_warning = _run_sparse_channel("bm25", self.bm25, query, per_channel_k)
            splade_pairs, splade_warning = _run_sparse_channel(
                "splade", self.splade, query, per_channel_k
            )
            if bm25_warning:
                warnings.append(bm25_warning)
            if splade_warning:
                warnings.append(splade_warning)

            semantic_pairs = _normalize_inputs(semantic_hits, per_channel_k)
            fusion_inputs: list[FusionInput] = []
            if semantic_pairs:
                fusion_inputs.append(FusionInput(channel="semantic", candidates=semantic_pairs))
            if bm25_pairs:
                fusion_inputs.append(FusionInput(channel="bm25", candidates=bm25_pairs))
            if splade_pairs:
                fusion_inputs.append(FusionInput(channel="splade", candidates=splade_pairs))

            if not fusion_inputs:
                return HybridSearchResult(
                    docs=[],
                    contributions={},
                    channels=[],
                    warnings=warnings or ["hybrid_search:no_candidates"],
                    method={
                        "channels": [],
                        "fusion": {"type": "weighted_rrf", "k": fusion_limit, "base": opts.rrf_base},
                        "weights": dict(opts.weights or {}),
                    },
                )

            weights = dict(opts.weights or {})
            fused_pairs = self.fusion.fuse(
                fusion_inputs,
                options=FusionOptions(weights=weights, k=fusion_limit, base=int(opts.rrf_base)),
            )
            limited_pairs = fused_pairs[:limit]
            docs = [
                HybridResultDoc(doc_id=str(doc_id), score=float(score))
                for doc_id, score in limited_pairs
            ]
            channels = [fi.channel for fi in fusion_inputs]
            contributions = {
                fi.channel: {
                    "candidates": len(fi.candidates),
                    "weight": float(weights.get(fi.channel, 1.0)),
                }
                for fi in fusion_inputs
            }
            method = {
                "channels": channels,
                "fusion": {
                    "type": "weighted_rrf",
                    "k": fusion_limit,
                    "base": int(opts.rrf_base),
                },
                "weights": weights,
                "per_channel_k": per_channel_k,
            }
            return HybridSearchResult(
                docs=docs,
                contributions=contributions,
                channels=channels,
                warnings=warnings,
                method=method,
            )


    def _run_sparse_channel(
        label: str,
        engine: BM25Engine | SPLADEEngine,
        query: str,
        limit: int,
    ) -> tuple[list[tuple[int, float]], str | None]:
        try:
            hits = engine.search(query, k=limit)
            pairs = [(int(doc_id), float(score)) for doc_id, score in hits]
            return pairs, None
        except Exception as exc:  # pragma: no cover
            return [], f"{label}_channel_error:{exc}"


    def _normalize_inputs(
        hits: Sequence[tuple[int, float]] | None,
        limit: int,
    ) -> list[tuple[int, float]]:
        if not hits:
            return []
        normalized: list[tuple[int, float]] = []
        for doc_id, score in hits[:limit]:
            try:
                normalized.append((int(doc_id), float(score)))
            except (TypeError, ValueError):
                continue
        return normalized
    """
).lstrip()


class RewriteHybridSearchStrictCommand(VisitorBasedCodemodCommand):
    """Replace ``codeintel_rev/io/hybrid_search.py`` with the canonical coordinator."""

    DESCRIPTION: str = __doc__ or ""

    def __init__(
        self,
        context: CodemodContext,
        *,
        path: str = "codeintel_rev/io/hybrid_search.py",
    ) -> None:
        """Initialize hybrid search strict rewrite command.

        Parameters
        ----------
        context : CodemodContext
            Codemod execution context.
        path : str, optional
            Target file path to rewrite (default: "codeintel_rev/io/hybrid_search.py").
        """
        super().__init__(context)
        self._target = Path(path)

    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        """Transform module AST, skipping if filename doesn't match target.

        Parameters
        ----------
        tree : cst.Module
            Module AST to transform.

        Returns
        -------
        cst.Module
            Transformed module AST or original if filename doesn't match.
        """
        filename = self.context.filename
        if filename is None:
            return tree
        current = Path(filename)
        if current.as_posix().endswith(self._target.as_posix()):
            return cst.parse_module(_COORDINATOR)
        return tree
