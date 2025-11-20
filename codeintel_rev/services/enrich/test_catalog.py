"""Test catalog building from pytest reports.

This module provides functions for parsing pytest JSON reports and building
test catalog artifacts. Maps pytest test nodes to function GOIDs using
qualified name matching, extracts test metadata (status, duration, markers),
and produces TestCatalogRow records for analytics.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from codeintel_rev.services.enrich.goid_utils import GOIDRow, build_qualname_index, normalize_path
from codeintel_rev.services.enrich.io import write_tabular_records


@dataclass(slots=True)
class TestCatalogRow:
    """Metadata for a single pytest test node."""

    test_id: str
    test_goid_h128: str | None
    urn: str | None
    repo: str
    commit: str
    rel_path: str
    qualname: str | None
    kind: str
    status: str
    duration_ms: float
    markers: list[str]
    parametrized: bool
    flaky: bool
    created_at: str


def _parse_nodeid(nodeid: str) -> tuple[str, str | None]:
    """Return (rel_path, qualname) parsed from a pytest nodeid.

    Extended Summary
    ----------------
    Parses a pytest test nodeid string to extract the file path and qualified
    function name. Handles parametrized test cases by stripping parameter
    markers from the qualname. Returns None for qualname if the nodeid doesn't
    contain a function qualifier.

    Parameters
    ----------
    nodeid : str
        Pytest test nodeid string (e.g., "path/to/test.py::TestClass::test_method[param]"
        or "path/to/test.py::test_function"). Must contain at least a file path.

    Returns
    -------
    tuple[str, str | None]
        Tuple containing (rel_path, qualname) where rel_path is the file path
        portion (may be relative or absolute) and qualname is the qualified
        function/class name (e.g., "TestClass.test_method") or None if no
        qualifier is present. Parameter markers are stripped from qualname.

    Notes
    -----
    Time O(1) for parsing; memory O(1) aside from string operations. No I/O.
    Thread-safe. Handles parametrized tests by splitting on "[" to remove
    parameter markers before building qualname.
    """
    path_part, *rest = nodeid.split("::")
    qualname = None
    if rest:
        base = rest[0]
        if "[" in base:
            base = base.split("[", 1)[0]
        qual_parts = [base, *rest[1:]]
        qualname = ".".join(qual_parts)
    return path_part, qualname


def _load_tests(report_path: Path) -> list[dict]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    tests = payload.get("tests", [])
    return [test for test in tests if isinstance(test, dict)]


def _lookup_test_goid(
    *,
    rel_path: str,
    qualname: str | None,
    goid_index: dict[tuple[str, str], GOIDRow],
) -> tuple[str | None, str | None]:
    if not qualname:
        return None, None
    key = (rel_path, qualname)
    match = goid_index.get(key)
    if match is None:
        return None, None
    return match.goid_h128, match.urn


def build_test_catalog(
    *,
    repo: str,
    commit: str,
    repo_root: Path,
    goids: Iterable[GOIDRow],
    pytest_report: Path,
) -> list[TestCatalogRow]:
    """Return rows describing collected pytest tests.

    Extended Summary
    ----------------
    Parses pytest JSON report to extract test metadata and builds test catalog
    rows. Maps test nodes to function GOIDs using qualified name matching,
    extracts test outcomes, durations, markers, and parametrization status.
    Produces TestCatalogRow records with test identifiers, GOID mappings,
    and test metadata for analytics.

    Parameters
    ----------
    repo : str
        Repository identifier to include in output rows.
    commit : str
        Commit hash to include in output rows.
    repo_root : Path
        Root directory of the repository. Used to normalize test file paths
        to repository-relative paths.
    goids : Iterable[GOIDRow]
        Iterable of GOID registry entries. Used to build qualname index for
        mapping test functions to GOIDs.
    pytest_report : Path
        Path to pytest JSON report generated via pytest-json-report plugin.
        File must exist and be readable. Should contain test collection and
        execution results.

    Returns
    -------
    list[TestCatalogRow]
        List of test catalog rows, one per pytest test node. Each row contains
        test_id (pytest nodeid), test_goid_h128 (if matched to GOID), urn,
        repository metadata, relative path, qualified name, test status,
        duration, markers, parametrization status, flaky flag, and timestamp.
        Rows are ordered by test nodeid.

    Notes
    -----
    Time O(n + m) where n is number of tests and m is number of GOIDs;
    memory O(n + m) for test catalog and GOID index. Performs file I/O to
    read pytest report. Thread-safe for separate instances. Tests without
    matching GOIDs have test_goid_h128 and urn set to None.
    """
    goid_index = build_qualname_index(goids)
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    rows: list[TestCatalogRow] = []
    for test in _load_tests(pytest_report):
        nodeid: str = str(test.get("nodeid") or "")
        outcome = str(test.get("outcome") or "unknown")
        duration_ms = float(test.get("duration") or 0.0) * 1000.0
        keywords = test.get("keywords") or {}

        raw_path, qualname = _parse_nodeid(nodeid)
        rel_path = normalize_path(raw_path, repo_root)
        test_goid, urn = _lookup_test_goid(
            rel_path=rel_path,
            qualname=qualname,
            goid_index=goid_index,
        )
        markers = sorted(
            key for key, value in keywords.items() if value and not str(key).startswith("@")
        )
        parametrized = "[" in nodeid and "]" in nodeid
        flaky = "flaky" in markers
        rows.append(
            TestCatalogRow(
                test_id=nodeid,
                test_goid_h128=test_goid,
                urn=urn,
                repo=repo,
                commit=commit,
                rel_path=rel_path,
                qualname=qualname,
                kind="parametrized_case" if parametrized else "function",
                status=outcome,
                duration_ms=duration_ms,
                markers=markers,
                parametrized=parametrized,
                flaky=flaky,
                created_at=now,
            )
        )
    return rows


def write_test_catalog(rows: Iterable[TestCatalogRow], out_path: Path) -> None:
    """Persist test catalog rows to Parquet and JSONL."""
    write_tabular_records(out_path, [asdict(row) for row in rows])
