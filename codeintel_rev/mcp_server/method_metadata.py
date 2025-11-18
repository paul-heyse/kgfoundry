"""Typed builders for MethodInfo payloads.

This module centralizes the logic for composing :class:`MethodInfo` structures
from the various retrieval adapters. The helpers validate required fields,
normalize Stage-0 metadata emitted by the hybrid pipeline, and ensure every
adapter returns a consistent payload for observability and testing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from codeintel_rev.mcp_server.schemas import (
    MethodGatingInfo,
    MethodInfo,
    MethodRerankerInfo,
    Stage0MethodInfo,
)


@dataclass(slots=True, frozen=True)
class MethodInfoComponents:
    """Bundle the optional pieces that make up a MethodInfo payload."""

    retrieval_channels: Sequence[str]
    coverage: str
    stage0: Mapping[str, object] | None = None
    gating: MethodGatingInfo | None = None
    reranker: MethodRerankerInfo | None = None

    def as_method_info(self) -> MethodInfo:
        """Return a :class:`MethodInfo` dict with normalized contents.

        Returns
        -------
        MethodInfo
            Payload containing normalized channel names, coverage string, and
            optional Stage-0, gating, and reranker metadata. Raises ``ValueError``
            if coverage is blank.

        Raises
        ------
        ValueError
            Raised when ``coverage`` is an empty string after trimming.
        """
        normalized_channels = _normalize_channels(self.retrieval_channels)
        coverage_text = self.coverage.strip()
        if not coverage_text:
            msg = "coverage must contain a non-empty description"
            raise ValueError(msg)

        method: MethodInfo = {
            "retrieval": normalized_channels,
            "coverage": coverage_text,
        }

        stage0_payload = normalize_stage0_method(self.stage0)
        if stage0_payload is not None:
            method["stage0"] = stage0_payload
        if self.gating is not None:
            method["gating"] = self.gating
        if self.reranker is not None:
            method["reranker"] = self.reranker
        return method


def normalize_stage0_method(payload: Mapping[str, object] | None) -> Stage0MethodInfo | None:
    """Normalize Stage-0 metadata to :class:`Stage0MethodInfo`.

    Parameters
    ----------
    payload : Mapping[str, object] | None
        Raw metadata returned by the hybrid search engine.

    Returns
    -------
    Stage0MethodInfo | None
        Sanitized Stage-0 metadata dictionary or ``None`` when no metadata was
        provided.
    """
    if not payload:
        return None

    normalized: Stage0MethodInfo = {}

    retrieval = _coerce_str_sequence(payload.get("retrieval"))
    if retrieval:
        normalized["retrieval"] = retrieval

    coverage = payload.get("coverage")
    if isinstance(coverage, str) and coverage.strip():
        normalized["coverage"] = coverage

    notes = _coerce_str_sequence(payload.get("notes"))
    if notes:
        normalized["notes"] = notes

    explainability = payload.get("explainability")
    if isinstance(explainability, Mapping):
        normalized["explainability"] = dict(explainability)

    fusion = payload.get("fusion")
    if isinstance(fusion, Mapping):
        normalized["fusion"] = dict(fusion)

    budget = payload.get("budget")
    if isinstance(budget, Mapping):
        normalized["budget"] = dict(budget)

    return normalized or None


def _coerce_str_sequence(value: object) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    return [str(item) for item in value]


def _normalize_channels(channels: Sequence[str]) -> list[str]:
    normalized = [str(name) for name in channels if str(name)]
    return list(dict.fromkeys(normalized or ["semantic"]))


__all__ = ["MethodInfoComponents", "normalize_stage0_method"]
