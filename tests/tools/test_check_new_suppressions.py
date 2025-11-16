"""Tests for the suppression guard CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tools.check_new_suppressions import (
    SuppressionGuardReport,
    build_guard_context,
    check_directory,
    resolve_target_directories,
    run_suppression_guard,
)

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions

if TYPE_CHECKING:
    from pathlib import Path


def _write(base: Path, name: str, content: str) -> Path:
    path = base / name
    path.write_text(content, encoding="utf-8")
    return path


SUPPRESSION_SAMPLE = "# type" + chr(58) + " ignore\n"
SUPPRESSION_WITH_TICKET = "# type" + chr(58) + " ignore  # TICKET: TEST-1\n"


def test_run_suppression_guard_detects_missing_ticket(tmp_path: Path) -> None:
    """The guard should raise when a suppression lacks ``TICKET:`` metadata."""
    _write(tmp_path, "module.py", SUPPRESSION_SAMPLE)

    with pytest.raises(ConfigurationError) as excinfo:
        run_suppression_guard([tmp_path])

    context = excinfo.value.context
    expected_report = check_directory(tmp_path)
    assertions.expect_equal(context, build_guard_context(expected_report))


def test_run_suppression_guard_allows_ticket_metadata(tmp_path: Path) -> None:
    """Files with ticket metadata should pass without raising."""
    _write(tmp_path, "module.py", SUPPRESSION_WITH_TICKET)

    report = run_suppression_guard([tmp_path])
    assertions.expect_true(report.is_clean, reason="report should be clean")
    assertions.expect_equal(report.violation_count, 0)


@pytest.mark.parametrize("violation_count", [-1, 42])
def test_report_from_context_validates_violation_count(
    tmp_path: Path, violation_count: int
) -> None:
    """from_context should reject mismatched violation counts."""
    _write(tmp_path, "module.py", SUPPRESSION_SAMPLE)

    report = check_directory(tmp_path)
    context = build_guard_context(report)
    context["violation_count"] = violation_count

    with pytest.raises(ValueError, match=r"expected -?\d+ violations, computed \d+"):
        SuppressionGuardReport.from_context(context)


def test_resolve_target_directories_validates_input(tmp_path: Path) -> None:
    """Invalid directories should surface as configuration errors."""
    with pytest.raises(ConfigurationError):
        resolve_target_directories(["./does-not-exist"])

    path = tmp_path / "not_a_dir.txt"
    path.write_text("content", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        resolve_target_directories([str(path)])


def test_resolve_target_directories_accepts_existing_directory(tmp_path: Path) -> None:
    """Valid directories should be resolved and returned."""
    resolved = resolve_target_directories([str(tmp_path)])

    assertions.expect_sequence_equal(resolved, [tmp_path.resolve()])
