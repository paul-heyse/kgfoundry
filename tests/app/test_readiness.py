# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Tests for filesystem readiness helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.app.readiness import (
    ReadinessError,
    check_directory,
    raise_on_errors,
    validate_paths,
)
from codeintel_rev.config.paths import resolve_application_paths


def test_check_directory_missing(tmp_path: Path) -> None:
    """A missing directory should trigger an error."""
    result = check_directory(tmp_path / "missing")
    assert result.status == "error"
    assert "missing" in result.message


def test_raise_on_errors(tmp_path: Path) -> None:
    """raise_on_errors should raise when any probe fails."""
    paths = resolve_application_paths({"BASE_DIR": tmp_path})
    results = validate_paths(paths)
    with pytest.raises(ReadinessError):
        raise_on_errors(results)
