"""Test-to-function coverage edge computation.

This module provides functions for computing test-to-function coverage edges
by analyzing coverage.py data with dynamic contexts. Maps test contexts to
covered functions, computes coverage ratios per test-function pair, and
produces TestCoverageEdgeRow records linking tests to the functions they cover.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import coverage

from codeintel_rev.services.enrich.coverage_functions import CoverageFunctionRow
from codeintel_rev.services.enrich.goid_utils import (
    FunctionSpan,
    lookup_function_for_line,
    normalize_path,
)
from codeintel_rev.services.enrich.io import write_tabular_records
from codeintel_rev.services.enrich.test_catalog import TestCatalogRow


@dataclass(slots=True)
class TestCoverageEdgeRow:
    """Coverage edge between a test and a function GOID."""

    test_id: str
    test_goid_h128: str | None
    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    qualname: str
    covered_lines: int
    executable_lines: int
    coverage_ratio: float | None
    last_status: str
    created_at: str


def _load_catalog(path: Path) -> dict[str, TestCatalogRow]:
    with path.open("r", encoding="utf-8") as handle:
        return {
            row.test_id: row
            for row in (TestCatalogRow(**json.loads(line)) for line in handle if line.strip())
        }


def _load_functions(path: Path) -> dict[str, CoverageFunctionRow]:
    with path.open("r", encoding="utf-8") as handle:
        return {
            row.function_goid_h128: row
            for row in (CoverageFunctionRow(**json.loads(line)) for line in handle if line.strip())
        }


def _contexts_by_line(data: coverage.CoverageData, abs_path: str) -> Mapping[int, Sequence[str]]:
    resolver = getattr(data, "contexts_by_lineno", None)
    if resolver is None:
        return {}
    return {int(line): tuple(ctxs or ()) for line, ctxs in resolver(abs_path).items()}


def build_test_coverage_edges(
    *,
    repo_root: Path,
    span_index: Mapping[str, Sequence[FunctionSpan]],
    coverage_file: Path,
    test_catalog_path: Path,
    coverage_functions_path: Path,
) -> list[TestCoverageEdgeRow]:
    """Return edges between tests and covered functions.

    Extended Summary
    ----------------
    Analyzes coverage.py data with dynamic contexts to compute test-to-function
    coverage relationships. For each covered line, identifies the containing
    function and the test context that executed it, then aggregates coverage
    counts per test-function pair. Produces TestCoverageEdgeRow records with
    coverage ratios and test status.

    Parameters
    ----------
    repo_root : Path
        Root directory of the repository. Used to normalize file paths to
        repository-relative paths for function span lookup.
    span_index : Mapping[str, Sequence[FunctionSpan]]
        Function span index mapping relative paths to sorted function spans.
        Used to map covered lines to their containing functions.
    coverage_file : Path
        Path to coverage.py data file (.coverage) with dynamic contexts enabled.
        File must exist and be readable. Context information is required for
        test-to-function mapping.
    test_catalog_path : Path
        Path to test catalog JSONL file. Must contain TestCatalogRow entries
        with test_id matching coverage context names.
    coverage_functions_path : Path
        Path to coverage functions JSONL file. Must contain CoverageFunctionRow
        entries with function_goid_h128 matching function spans.

    Returns
    -------
    list[TestCoverageEdgeRow]
        List of test-to-function coverage edges. Each edge links a test (by
        test_id) to a function (by function_goid_h128) with covered_lines count,
        executable_lines count, coverage_ratio, and test status. Edges are
        ordered by test_id and function_goid_h128.

    Notes
    -----
    Time O(n * m) where n is number of covered lines and m is average contexts
    per line; memory O(n + m) for loading test catalog, function spans, and
    coverage data. Performs file I/O to read coverage data, test catalog, and
    coverage functions. Thread-safe for separate instances. Requires coverage
    data collected with dynamic contexts enabled. Files outside repository tree
    are skipped silently.
    """
    tests_by_id = _load_catalog(test_catalog_path)
    functions_by_goid = _load_functions(coverage_functions_path)
    cov = coverage.Coverage(data_file=str(coverage_file))
    cov.load()
    data = cov.get_data()
    timestamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

    counts: dict[tuple[str, str], int] = {}
    for abs_path in data.measured_files():
        try:
            rel_path = normalize_path(abs_path, repo_root)
        except ValueError:
            continue
        contexts_by_line = _contexts_by_line(data, abs_path)
        if not contexts_by_line:
            continue
        for line, contexts in contexts_by_line.items():
            span = lookup_function_for_line(
                index_by_path=span_index,
                rel_path=rel_path,
                line=line,
            )
            if span is None:
                continue
            for ctx in contexts:
                test_row = tests_by_id.get(ctx)
                if test_row is None:
                    continue
                key = (ctx, span.goid_h128)
                counts[key] = counts.get(key, 0) + 1

    edges: list[TestCoverageEdgeRow] = []
    for (test_id, func_goid), covered_lines in counts.items():
        func_row = functions_by_goid.get(func_goid)
        test_row = tests_by_id.get(test_id)
        if func_row is None or test_row is None:
            continue
        exec_lines = func_row.executable_lines
        coverage_ratio = None if exec_lines == 0 else covered_lines / exec_lines
        edges.append(
            TestCoverageEdgeRow(
                test_id=test_id,
                test_goid_h128=test_row.test_goid_h128,
                function_goid_h128=func_goid,
                urn=func_row.urn,
                repo=func_row.repo,
                commit=func_row.commit,
                rel_path=func_row.rel_path,
                qualname=func_row.qualname,
                covered_lines=covered_lines,
                executable_lines=exec_lines,
                coverage_ratio=coverage_ratio,
                last_status=test_row.status,
                created_at=timestamp,
            )
        )
    return edges


def write_test_coverage_edges(rows: Iterable[TestCoverageEdgeRow], out_path: Path) -> None:
    """Persist test coverage edges to Parquet and JSONL."""
    write_tabular_records(out_path, [asdict(row) for row in rows])
