"""Lightweight heuristics over run reports to surface diagnostics hints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

StageRecord = Mapping[str, Any]

_SMALL_BATCH_THRESHOLD = 4
_AMBIGUITY_THRESHOLD = 0.3
_SHALLOW_RRF_THRESHOLD = 50


def _stage_by_prefix(stages: Sequence[StageRecord], prefixes: Sequence[str]) -> StageRecord | None:
    for stage in stages:
        name = str(stage.get("name") or "")
        if any(name.startswith(prefix) for prefix in prefixes):
            return stage
    return None


def _stage_attr(stage: StageRecord | None, key: str) -> object | None:
    if not stage:
        return None
    attrs = stage.get("attrs")
    if isinstance(attrs, Mapping):
        return attrs.get(key)
    return None


def _collect_mapping(report: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    candidate = report.get(key)
    if isinstance(candidate, Mapping):
        return candidate
    return {}


def _collect_stages(report: Mapping[str, Any]) -> Sequence[StageRecord]:
    stages = report.get("stages")
    if isinstance(stages, Sequence):
        return stages
    return ()


def _gap_hint(ops: Mapping[str, Any]) -> dict[str, Any] | None:
    if ops.get("fuse") and not ops.get("hydrate"):
        return {
            "kind": "gap:hydrate",
            "msg": "Results were fused but never hydrated: check DuckDB/catalog availability.",
            "why": {"ops_coverage": dict(ops)},
        }
    return None


def _sparse_hint(ops: Mapping[str, Any], budgets: Mapping[str, Any]) -> dict[str, Any] | None:
    if budgets.get("rm3_enabled") and not ops.get("sparse"):
        return {
            "kind": "config:sparse-disabled",
            "msg": "RM3 enabled but sparse channels skipped; ensure BM25/SPLADE assets are healthy.",
            "why": {"budgets": dict(budgets), "ops_coverage": dict(ops)},
        }
    return None


def _vllm_hints(stages: Sequence[StageRecord]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    embed_stage = _stage_by_prefix(stages, ("search.embed", "coderank.embed"))
    batch_size = _stage_attr(embed_stage, "batch") or _stage_attr(embed_stage, "batch_size")
    if isinstance(batch_size, int) and 0 < batch_size < _SMALL_BATCH_THRESHOLD:
        hints.append(
            {
                "kind": "perf:batch",
                "msg": "Embedding batches are very small; consider increasing batch size.",
                "why": {"batch": batch_size},
            }
        )
    mode = _stage_attr(embed_stage, "mode")
    if isinstance(mode, str) and mode.lower() == "http":
        hints.append(
            {
                "kind": "perf:mode",
                "msg": "vLLM running over HTTP; in-process mode reduces latency.",
                "why": {"mode": mode},
            }
        )
    return hints


def _faiss_hint(stages: Sequence[StageRecord]) -> dict[str, Any] | None:
    stage = _stage_by_prefix(stages, ("search.faiss",))
    if stage is None:
        return None
    gpu_ready = _stage_attr(stage, "gpu_ready")
    if gpu_ready is None:
        gpu_ready = _stage_attr(stage, "faiss.gpu")
    if gpu_ready is False:
        return {
            "kind": "degrade:faiss-cpu",
            "msg": "FAISS GPU path unavailable; queries are running on CPU.",
            "why": {"gpu_ready": gpu_ready},
        }
    return None


def _rrf_hint(budgets: Mapping[str, Any]) -> dict[str, Any] | None:
    ambiguity = budgets.get("ambiguity_score") or budgets.get("ambiguity")
    rrf_k = budgets.get("rrf_k")
    if (
        isinstance(ambiguity, (int, float))
        and ambiguity > _AMBIGUITY_THRESHOLD
        and isinstance(rrf_k, (int, float))
        and rrf_k < _SHALLOW_RRF_THRESHOLD
    ):
        return {
            "kind": "budget:rrf",
            "msg": "Vague query with shallow RRF budget; consider increasing rrf_k.",
            "why": {"ambiguity": ambiguity, "rrf_k": rrf_k},
        }
    return None


def detect(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return structured hints derived from the run report payload.

    This function analyzes a run report and generates diagnostic hints based on
    patterns in operations coverage, budget allocations, and stage execution. It is
    called by diagnostic tools to provide actionable insights about search
    performance and configuration issues.

    Parameters
    ----------
    report : Mapping[str, Any]
        Run report dictionary containing events, operations coverage, budgets,
        and stage information.

    Returns
    -------
    list[dict[str, Any]]
        Collection of diagnostic hints with ``kind``, ``msg``, and ``why`` fields.
        Each hint describes a potential issue or optimization opportunity detected
        in the report.
    """
    hints: list[dict[str, Any]] = []
    ops = _collect_mapping(report, "ops_coverage")
    budgets = _collect_mapping(report, "budgets") or _collect_mapping(report, "gating")
    stages = _collect_stages(report)

    gap_hint = _gap_hint(ops)
    if gap_hint:
        hints.append(gap_hint)
    sparse_hint = _sparse_hint(ops, budgets)
    if sparse_hint:
        hints.append(sparse_hint)
    hints.extend(_vllm_hints(stages))
    faiss_hint = _faiss_hint(stages)
    if faiss_hint:
        hints.append(faiss_hint)
    rrf_hint = _rrf_hint(budgets)
    if rrf_hint:
        hints.append(rrf_hint)
    return hints


__all__ = ["detect"]
