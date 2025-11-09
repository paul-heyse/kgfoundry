"""Tests for PR summary generation utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.generate_pr_summary import collect_artifact_snapshot, generate_summary

if TYPE_CHECKING:
    from pathlib import Path


def test_collect_artifact_snapshot_detects_numbered_codemod_logs(
    tmp_path: Path,
) -> None:
    """Snapshot should include all codemod log files with numeric suffixes."""
    (tmp_path / "codemod.log").write_text("root run\n")
    (tmp_path / "codemod_r1.log").write_text("run 1\n")
    (tmp_path / "codemod_r2.log").write_text("run 2\n")
    (tmp_path / "codemod_r3.txt").write_text("not a log\n")

    snapshot = collect_artifact_snapshot(tmp_path)

    assert snapshot.codemod_logs == (
        "codemod.log",
        "codemod_r1.log",
        "codemod_r2.log",
    )


def test_collect_artifact_snapshot_orders_double_digit_logs(tmp_path: Path) -> None:
    """Codemod logs should be sorted using natural order for numeric suffixes."""
    (tmp_path / "codemod_r10.log").write_text("run 10\n")
    (tmp_path / "codemod.log").write_text("root run\n")
    (tmp_path / "codemod_r2.log").write_text("run 2\n")

    snapshot = collect_artifact_snapshot(tmp_path)

    assert snapshot.codemod_logs == (
        "codemod.log",
        "codemod_r2.log",
        "codemod_r10.log",
    )


def test_generate_summary_lists_all_codemod_logs(tmp_path: Path) -> None:
    """Rendered summary should include every detected codemod log entry."""
    for name in ("codemod.log", "codemod_r7.log"):
        (tmp_path / name).write_text("log contents\n")

    snapshot = collect_artifact_snapshot(tmp_path)
    summary = generate_summary(snapshot=snapshot, checks=())

    assert "`codemod.log`" in summary
    assert "`codemod_r7.log`" in summary
    assert summary.count("Codemod execution log") == 2


def test_generate_summary_with_empty_checks_emits_only_headers(tmp_path: Path) -> None:
    """Explicit empty checks should result in no table rows beyond the header."""
    snapshot = collect_artifact_snapshot(tmp_path)
    summary = generate_summary(snapshot=snapshot, checks=())

    table_lines = [line for line in summary.splitlines() if line.startswith("|")]

    assert table_lines == ["| Check | Status |", "|-------|--------|"]
