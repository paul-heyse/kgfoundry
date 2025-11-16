"""Shared magic-number replacements used across the test-suite."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VectorDimensions:
    """Standard vector dimensionalities used by FAISS-focused tests."""

    pair: int = 2
    tiny: int = 3
    small: int = 4
    base_top_k: int = 5
    rerank_candidate_count: int = 8


@dataclass(frozen=True)
class Timeouts:
    """Shared timeout thresholds for integration/benchmark suites (seconds)."""

    incremental_regression: float = 60.0
    git_history_backoff: float = 40.0


@dataclass(frozen=True)
class BatchSizes:
    """Common batch sizes used by CLI and embedding tests."""

    minimal: int = 2
    small: int = 3
    medium: int = 4
    large: int = 5


VECTOR_DIMS = VectorDimensions()
TIMEOUTS = Timeouts()
BATCH_SIZES = BatchSizes()
