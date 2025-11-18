"""Tests for filesystem readiness probes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from codeintel_rev.app import readiness
from codeintel_rev.config.paths import resolve_application_paths

from tests._helpers.assertions import expect_equal, expect_true
from tests._helpers.settings import build_settings_for_repo


def _prepare_paths(repo_root: Path) -> None:
    repo_root.mkdir()
    for relative in (
        "config",
        "data",
        "data/vectors",
        "logs",
        ".cache",
        ".tmp",
        "plugins",
    ):
        (repo_root / relative).mkdir(parents=True, exist_ok=True)
    (repo_root / "config" / "config.yaml").write_text("tests: true")


def test_check_file_reports_missing(tmp_path: Path) -> None:
    """check_file returns an error when the file is absent."""
    target = tmp_path / "missing.cfg"
    result = readiness.check_file(target)
    expect_equal(result.status, "error", reason="missing files flagged")
    expect_true("missing" in result.message, reason="error message mentions missing file")


@pytest.mark.skipif(os.name == "nt", reason="chmod semantics vary on Windows")
def test_check_directory_detects_permissions(tmp_path: Path) -> None:
    """check_directory reports unwritable directories."""
    target = tmp_path / "locked"
    target.mkdir()
    target.chmod(0o500)

    result = readiness.check_directory(target)

    expect_equal(result.status, "error", reason="permission errors detected")
    expect_true("writable" in result.message, reason="message references missing permission")


def test_validate_paths_and_raise(tmp_path: Path) -> None:
    """validate_paths returns ok for healthy structures and raises on errors."""
    repo_root = tmp_path / "repo"
    _prepare_paths(repo_root)
    settings = build_settings_for_repo(repo_root)
    paths = resolve_application_paths(settings)

    results = readiness.validate_paths(paths)

    expect_true(all(res.status == "ok" for res in results), reason="healthy repo passes probes")

    # Remove data_dir to trigger a readiness error
    shutil.rmtree(paths.data_dir)
    results = readiness.validate_paths(paths)
    with pytest.raises(readiness.ReadinessError):
        readiness.raise_on_errors(results)
