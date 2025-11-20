"""Coverage function aggregation and analytics.

This module provides functions for aggregating per-line coverage data into
per-function coverage metrics. Processes coverage line rows and function GOIDs
to compute executable lines, covered lines, coverage ratios, and test status
for each function in the codebase.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from codeintel_rev.services.enrich.coverage_lines import CoverageLineRow
from codeintel_rev.services.enrich.goid_utils import (
    GOIDRow,
    build_function_span_index,
    lookup_function_for_line,
)
from codeintel_rev.services.enrich.io import write_tabular_records


@dataclass(slots=True)
class CoverageFunctionRow:
    """Aggregated coverage metrics for a single function GOID."""

    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    executable_lines: int
    covered_lines: int
    coverage_ratio: float | None
    tested: bool
    untested_reason: str
    created_at: str


LOGGER = logging.getLogger(__name__)


def _load_coverage_line_rows(path: Path) -> Iterator[CoverageLineRow]:
    """Load coverage line rows from JSONL file.

    Extended Summary
    ----------------
    Reads a JSONL file containing coverage line data and yields CoverageLineRow
    instances. Skips empty lines and tolerates malformed JSON by logging and
    continuing, rather than failing the aggregation.

    Parameters
    ----------
    path : Path
        Path to JSONL file containing coverage line data. File must exist and
        be readable. Each line should be a JSON object matching CoverageLineRow
        structure.

    Yields
    ------
    CoverageLineRow
        Coverage line row parsed from JSONL file. One row per non-empty line.

    Notes
    -----
    Time O(n) where n is the number of lines; memory O(1) aside from line buffer.
    Performs file I/O to read the JSONL file. Thread-safe for separate file handles.
    """
    if not path.exists():
        LOGGER.warning("coverage lines file missing at %s", path)
        return
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "Skipping malformed coverage line %s:%d: %s",
                    path,
                    lineno,
                    exc.msg,
                )
                continue
            if not isinstance(payload, dict):
                LOGGER.warning("Skipping non-object coverage line %s:%d", path, lineno)
                continue
            try:
                yield CoverageLineRow(**payload)
            except TypeError as exc:
                LOGGER.warning(
                    "Skipping invalid coverage line %s:%d: %s",
                    path,
                    lineno,
                    exc,
                )


def _bump_count(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def aggregate_coverage_functions(
    *,
    goids: Iterable[GOIDRow],
    coverage_lines_path: Path,
    repo: str = "",
    commit: str = "",
) -> list[CoverageFunctionRow]:
    """Aggregate per-line coverage into per-function metrics.

    Extended Summary
    ----------------
    Processes coverage line data and function GOIDs to compute aggregated
    coverage metrics per function. Builds a function span index from GOIDs,
    then iterates through coverage lines to count executable and covered lines
    for each function. Computes coverage ratios and test status, producing
    CoverageFunctionRow records for analytics.

    Parameters
    ----------
    goids : Iterable[GOIDRow]
        Iterable of function GOID rows containing function span information
        (goid_h128, urn, rel_path, start_line, end_line, kind, qualname).
    coverage_lines_path : Path
        Path to JSONL file containing per-line coverage data. File must exist
        and be readable. Each line should be a CoverageLineRow JSON object.
    repo : str, optional
        Repository identifier to include in output records. If empty, extracted
        from first GOID row if available. Defaults to "".
    commit : str, optional
        Commit hash to include in output records. If empty, extracted from first
        GOID row if available. Defaults to "".

    Returns
    -------
    list[CoverageFunctionRow]
        List of aggregated coverage metrics per function. Each record contains
        function identifier, location, executable lines count, covered lines count,
        coverage ratio (0.0-1.0 or None if no executable lines), tested status,
        and untested reason. Records are ordered by rel_path and function span.

    Notes
    -----
    Time O(n + m) where n is number of GOIDs and m is number of coverage lines;
    memory O(n) for function span index and coverage counts. Performs file I/O
    to read coverage_lines_path. Thread-safe for separate instances processing
    different files. Coverage ratio is computed as covered_lines / executable_lines
    when executable_lines > 0, otherwise None.
    """
    goid_rows = list(goids)
    index_by_path = build_function_span_index(goid_rows)
    counts: dict[str, dict[str, int]] = {}

    for row in _load_coverage_line_rows(coverage_lines_path):
        if not row.is_executable:
            continue
        span = lookup_function_for_line(
            index_by_path=index_by_path,
            rel_path=row.rel_path,
            line=row.line,
        )
        if span is None:
            continue
        bucket = counts.setdefault(span.goid_h128, {"exec": 0, "cov": 0})
        _bump_count(bucket, "exec")
        if row.is_covered:
            _bump_count(bucket, "cov")

    timestamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    repo_value = repo or (goid_rows[0].repo if goid_rows else "")
    commit_value = commit or (goid_rows[0].commit if goid_rows else "")
    records: list[CoverageFunctionRow] = []
    for rel_path, spans in index_by_path.items():
        for span in spans:
            tally = counts.get(span.goid_h128, {"exec": 0, "cov": 0})
            exec_lines = tally["exec"]
            cov_lines = tally["cov"]
            coverage_ratio = None if exec_lines == 0 else cov_lines / exec_lines
            tested = cov_lines > 0
            if exec_lines == 0:
                reason = "no_executable_code"
            elif not tested:
                reason = "no_tests"
            else:
                reason = ""
            records.append(
                CoverageFunctionRow(
                    function_goid_h128=span.goid_h128,
                    urn=span.urn,
                    repo=repo_value,
                    commit=commit_value,
                    rel_path=rel_path,
                    language="python",
                    kind=span.kind,
                    qualname=span.qualname,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    executable_lines=exec_lines,
                    covered_lines=cov_lines,
                    coverage_ratio=coverage_ratio,
                    tested=tested,
                    untested_reason=reason,
                    created_at=timestamp,
                )
            )
    return records


def write_coverage_functions(rows: Iterable[CoverageFunctionRow], out_path: Path) -> None:
    """Persist per-function coverage rows to Parquet and JSONL."""
    write_tabular_records(out_path, [asdict(row) for row in rows])
