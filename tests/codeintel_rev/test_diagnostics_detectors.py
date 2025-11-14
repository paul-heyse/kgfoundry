from __future__ import annotations

from codeintel_rev.diagnostics.detectors import detect


def test_detect_flags_common_gaps() -> None:
    report = {
        "ops_coverage": {
            "embed": True,
            "dense": True,
            "sparse": False,
            "gather": True,
            "fuse": True,
            "hydrate": False,
        },
        "budgets": {
            "rm3_enabled": True,
            "ambiguity_score": 0.5,
            "rrf_k": 25,
        },
        "stages": [
            {"name": "search.embed", "attrs": {"batch": 1, "mode": "http"}},
            {"name": "search.faiss", "attrs": {"gpu_ready": False}},
        ],
    }
    hints = detect(report)
    kinds = {hint["kind"] for hint in hints}
    assert "gap:hydrate" in kinds
    assert "config:sparse-disabled" in kinds
    assert "perf:batch" in kinds
    assert "perf:mode" in kinds
    assert "degrade:faiss-cpu" in kinds
    assert "budget:rrf" in kinds
