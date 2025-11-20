"""Coverage line extraction and analytics.

This module provides functions for extracting per-line coverage data from
coverage.py data files and writing coverage line records. Processes coverage
data to identify executable lines, covered lines, hit counts, and context
information for each line in measured files.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import coverage

from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path
from codeintel_rev.services.enrich.io import write_tabular_records


@dataclass(slots=True)
class CoverageLineRow:
    """Single line-level coverage record."""

    repo: str
    commit: str
    rel_path: str
    line: int
    is_executable: bool
    is_covered: bool
    hits: int
    context_count: int
    created_at: str


def _analysis_for_file(cov: coverage.Coverage, abs_path: str) -> tuple[set[int], set[int]]:
    """Return executable and executed lines for a file.

    Extended Summary
    ----------------
    Analyzes a single file's coverage data to determine which lines are
    executable and which were actually executed. Uses coverage.py's analysis2
    method to extract statement and missing line information.

    Parameters
    ----------
    cov : coverage.Coverage
        Coverage.py Coverage instance with loaded coverage data.
    abs_path : str
        Absolute path to the source file to analyze. Must be a measured file
        in the coverage data.

    Returns
    -------
    tuple[set[int], set[int]]
        Tuple containing (executable_lines, executed_lines) where executable_lines
        is the set of all executable line numbers and executed_lines is the subset
        that were actually executed during test runs.
    """
    _, statements, _, missing, _ = cov.analysis2(abs_path)
    executable = {int(line) for line in statements}
    missing_set = {int(line) for line in missing}
    executed = executable.difference(missing_set)
    return executable, executed


def _contexts_by_line(data: coverage.CoverageData, abs_path: str) -> dict[int, Sequence[str]]:
    """Return mapping of line -> contexts if available.

    Extended Summary
    ----------------
    Extracts dynamic context information for each line if the coverage data
    was collected with dynamic contexts enabled. Returns empty dict if contexts
    are not available.

    Parameters
    ----------
    data : coverage.CoverageData
        Coverage.py CoverageData instance containing coverage measurements.
    abs_path : str
        Absolute path to the source file. Must be a measured file in the
        coverage data.

    Returns
    -------
    dict[int, Sequence[str]]
        Mapping from line number to sequence of context names (test names or
        other dynamic contexts) that executed that line. Empty dict if contexts
        are not available or if the file has no context information.
    """
    resolver = getattr(data, "contexts_by_lineno", None)
    if resolver is None:
        return {}
    contexts = resolver(abs_path)
    return {int(line): tuple(value or ()) for line, value in contexts.items()}


def iter_coverage_lines(
    *,
    repo: str,
    commit: str,
    repo_root: Path,
    coverage_file: Path,
) -> Iterator[CoverageLineRow]:
    """Yield line-level coverage rows from a coverage.py data file.

    Extended Summary
    ----------------
    Processes a coverage.py data file to extract per-line coverage information
    for all measured files. For each executable line in each file, yields a
    CoverageLineRow containing line number, coverage status, hit count, and
    context information. Files outside the repository tree are skipped.

    Parameters
    ----------
    repo : str
        Repository identifier to include in output rows.
    commit : str
        Commit hash to include in output rows.
    repo_root : Path
        Root directory of the repository. Used to compute relative paths
        and filter files outside the repository tree.
    coverage_file : Path
        Path to coverage.py data file (.coverage). File must exist and be
        readable. Should contain coverage data collected with dynamic contexts
        enabled for context_count to be meaningful.

    Yields
    ------
    CoverageLineRow
        Coverage line row for each executable line in measured files. Contains
        repository metadata, relative path, line number, executable/covered
        status, hit count, context count, and timestamp. Rows are ordered by
        file path and line number.

    Notes
    -----
    Time O(n) where n is the number of executable lines across all files;
    memory O(m) where m is the number of contexts per file. Performs file I/O
    to load coverage data. Thread-safe for separate Coverage instances.
    Files that cannot be normalized relative to repo_root are skipped silently.
    """
    cov = coverage.Coverage(data_file=str(coverage_file))
    cov.load()
    data = cov.get_data()
    timestamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

    for abs_path in data.measured_files():
        abs_path_obj = Path(abs_path)
        try:
            rel_path = normalized_rel_path(abs_path_obj, repo_root)
        except ValueError:
            # Ignore files outside the repository tree.
            continue
        executable, executed = _analysis_for_file(cov, abs_path)
        contexts = _contexts_by_line(data, abs_path)
        for line in sorted(executable):
            is_covered = line in executed
            yield CoverageLineRow(
                repo=repo,
                commit=commit,
                rel_path=rel_path,
                line=line,
                is_executable=True,
                is_covered=is_covered,
                hits=1 if is_covered else 0,
                context_count=len(contexts.get(line, ())),
                created_at=timestamp,
            )


def write_coverage_lines(rows: Iterable[CoverageLineRow], out_path: Path) -> None:
    """Persist coverage line rows to Parquet and JSONL."""
    payload = [asdict(row) for row in rows]
    write_tabular_records(out_path, payload)
