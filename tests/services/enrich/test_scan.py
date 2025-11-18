# SPDX-License-Identifier: MIT
"""Tests for scan service helpers."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.services.enrich import scan

from tests._helpers import assertions


def test_iter_python_files_skips_hidden_and_auxiliary_dirs(tmp_path: Path) -> None:
    """Verify iter_python_files excludes hidden, stubs, and overlays directories."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".venv").mkdir()
    (repo / ".venv" / "ignored.py").write_text("", encoding="utf-8")
    (repo / "stubs").mkdir()
    (repo / "stubs" / "overlay.py").write_text("", encoding="utf-8")
    (repo / "pkg").mkdir()
    target = repo / "pkg" / "app.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    discovered = list(scan.iter_python_files(repo))
    assertions.expect_sequence_equal(discovered, [target.resolve()])


def test_discover_python_files_honors_patterns(tmp_path: Path) -> None:
    """Ensure discover_python_files respects include globs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pkg").mkdir()
    (repo / "pkg" / "app.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "internal.py").write_text("", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("", encoding="utf-8")

    files = scan.discover_python_files(repo, ("pkg/app.py",))
    assertions.expect_sequence_equal(files, [repo / "pkg" / "app.py"])
