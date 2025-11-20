"""Tests for coverage analytics and risk factor computation."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from codeintel_rev.services.enrich.coverage_functions import aggregate_coverage_functions
from codeintel_rev.services.enrich.goid_utils import (
    GOIDRow,
    build_function_span_index,
    lookup_function_for_line,
)
from codeintel_rev.services.enrich.risk_factors import build_goid_risk_factors

EXPECTED_COVERAGE_RATIO = 0.5
EXPECTED_LINES = 2
EXPECTED_RISK_COVERAGE = 0.2


def check(*, condition: bool, msg: str = "") -> None:
    """Assert condition is true, else fail test."""
    if not condition:
        pytest.fail(msg or "Check failed")


def _goid(
    *,
    goid_h128: str,
    rel_path: str,
    qualname: str,
    start: int,
    end: int,
) -> GOIDRow:
    return GOIDRow(
        goid_h128=goid_h128,
        urn=f"urn:{goid_h128}",
        repo="repo",
        commit="commit",
        rel_path=rel_path,
        language="python",
        kind="function",
        qualname=qualname,
        start_line=start,
        end_line=end,
    )


def test_lookup_function_prefers_inner_span() -> None:
    """Verify that lookup prefers the innermost function span."""
    goids = [
        _goid(goid_h128="1", rel_path="pkg/mod.py", qualname="outer", start=10, end=40),
        _goid(goid_h128="2", rel_path="pkg/mod.py", qualname="inner", start=20, end=25),
    ]
    index = build_function_span_index(goids)
    span = lookup_function_for_line(index_by_path=index, rel_path="pkg/mod.py", line=22)
    check(condition=span is not None, msg="span should be found")
    if span:
        check(
            condition=span.goid_h128 == "2",
            msg=f"expected '2', got {span.goid_h128}",
        )
        check(condition=span.qualname == "inner", msg=f"expected 'inner', got {span.qualname}")
    check(
        condition=lookup_function_for_line(index_by_path=index, rel_path="pkg/mod.py", line=5)
        is None,
        msg="should not find span for line 5",
    )


def test_aggregate_coverage_functions_counts(tmp_path: Path) -> None:
    """Test aggregation of coverage lines into function metrics."""
    goids = [
        _goid(goid_h128="101", rel_path="pkg/mod.py", qualname="fn", start=1, end=4),
    ]
    coverage_lines_jsonl = tmp_path / "coverage_lines.jsonl"
    coverage_lines_jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "repo": "repo",
                        "commit": "commit",
                        "rel_path": "pkg/mod.py",
                        "line": 1,
                        "is_executable": True,
                        "is_covered": True,
                        "hits": 1,
                        "context_count": 1,
                        "created_at": "now",
                    }
                ),
                json.dumps(
                    {
                        "repo": "repo",
                        "commit": "commit",
                        "rel_path": "pkg/mod.py",
                        "line": 2,
                        "is_executable": True,
                        "is_covered": False,
                        "hits": 0,
                        "context_count": 0,
                        "created_at": "now",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    rows = aggregate_coverage_functions(goids=goids, coverage_lines_path=coverage_lines_jsonl)
    check(condition=len(rows) == 1, msg="expected 1 row")
    row = rows[0]
    check(condition=row.function_goid_h128 == "101", msg="goid mismatch")
    check(condition=row.executable_lines == EXPECTED_LINES, msg="exec lines mismatch")
    check(condition=row.covered_lines == 1, msg="covered lines mismatch")
    check(condition=row.coverage_ratio == EXPECTED_COVERAGE_RATIO, msg="ratio mismatch")
    check(condition=row.tested is True, msg="tested mismatch")


def test_build_goid_risk_factors(tmp_path: Path) -> None:
    """Test construction of risk factors from multiple sources."""
    analytics_dir = tmp_path / "analytics"
    coverage_dir = analytics_dir / "coverage"
    tests_dir = analytics_dir / "tests"
    risk_dir = analytics_dir / "risk"
    goid_dir = tmp_path / "goid"
    modules_dir = tmp_path / "modules"
    coverage_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    risk_dir.mkdir(parents=True)
    goid_dir.mkdir(parents=True)
    modules_dir.mkdir(parents=True)

    # Minimal GOID registry to satisfy span loading.
    con = duckdb.connect()
    con.execute(
        """
        COPY (
            SELECT
                CAST(goid_h128 AS DOUBLE) AS goid_h128,
                urn,
                repo,
                commit,
                rel_path,
                language,
                kind,
                qualname,
                start_line,
                end_line
            FROM (
                SELECT
                    9.99e2 AS goid_h128,
                    'urn:999' AS urn,
                    'repo' AS repo,
                    'commit' AS commit,
                    'pkg/mod.py' AS rel_path,
                    'python' AS language,
                    'function' AS kind,
                    'fn' AS qualname,
                    1 AS start_line,
                    5 AS end_line
            )
        ) TO ?
        (FORMAT PARQUET)
        """,
        [str(goid_dir / "goids.parquet")],
    )
    con.close()

    coverage_functions = {
        "function_goid_h128": "999",
        "urn": "urn:999",
        "repo": "repo",
        "commit": "commit",
        "rel_path": "pkg/mod.py",
        "language": "python",
        "kind": "function",
        "qualname": "fn",
        "start_line": 1,
        "end_line": 5,
        "executable_lines": 5,
        "covered_lines": 1,
        "coverage_ratio": 0.2,
        "tested": True,
        "untested_reason": "",
        "created_at": "now",
    }
    (coverage_dir / "coverage_functions.jsonl").write_text(
        json.dumps(coverage_functions), encoding="utf-8"
    )

    function_metrics = {
        "function_goid_h128": "999",
        "urn": "urn:999",
        "repo": "repo",
        "commit": "commit",
        "rel_path": "pkg/mod.py",
        "language": "python",
        "kind": "function",
        "qualname": "fn",
        "start_line": 1,
        "end_line": 5,
        "loc": 10,
        "logical_loc": 8,
        "cyclomatic_complexity": 7,
        "complexity_bucket": "high",
    }
    (analytics_dir / "function_metrics.jsonl").write_text(
        json.dumps(function_metrics), encoding="utf-8"
    )
    function_types = {
        "function_goid_h128": "999",
        "typedness_bucket": "untyped",
        "typedness_source": "annotations",
    }
    (analytics_dir / "function_types.jsonl").write_text(
        json.dumps(function_types), encoding="utf-8"
    )
    con = duckdb.connect()
    con.execute(
        """
        COPY (
            SELECT
                'pkg/mod.py' AS path,
                9.5 AS hotspot_score,
                0 AS fan_in,
                0 AS fan_out,
                0 AS type_error_count,
                0 AS used_by_files
        ) TO ?
        (FORMAT PARQUET)
        """,
        [str(analytics_dir / "hotspots.parquet")],
    )
    con.execute(
        """
        COPY (
            SELECT
                'pkg/mod.py' AS path,
                0 AS type_error_count,
                STRUCT_PACK(params:=0.2, "returns":=0.2) AS annotation_ratio,
                0 AS untyped_defs,
                false AS overlay_needed
        ) TO ?
        (FORMAT PARQUET)
        """,
        [str(analytics_dir / "typedness.parquet")],
    )
    con.execute(
        """
        COPY (
            SELECT
                'pkg/mod.py' AS rel_path,
                1 AS pyrefly_errors,
                1 AS pyright_errors,
                2 AS total_errors,
                true AS has_errors
        ) TO ?
        (FORMAT PARQUET)
        """,
        [str(analytics_dir / "static_diagnostics.parquet")],
    )
    con.close()
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / "modules.jsonl").write_text(
        json.dumps({"path": "pkg/mod.py", "tags": ["api"], "owners": ["team"]}),
        encoding="utf-8",
    )

    rows = build_goid_risk_factors(tmp_path)
    check(condition=len(rows) == 1, msg="expected 1 row")
    row = rows[0]
    check(condition=row.function_goid_h128 == "999", msg="goid mismatch")
    check(condition=row.coverage_ratio == EXPECTED_RISK_COVERAGE, msg="ratio mismatch")
    check(condition=row.complexity_bucket == "high", msg="complexity mismatch")
    check(condition=row.typedness_bucket == "untyped", msg="typedness mismatch")
    check(condition=row.risk_level in {"medium", "high"}, msg="risk level mismatch")
    check(condition=row.tags == ["api"], msg="tags mismatch")
    check(condition=row.owners == ["team"], msg="owners mismatch")
