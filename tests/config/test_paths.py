# ruff: noqa: S101 - pytest assertions are intentional.
"""Tests for application path resolution configuration."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.config.paths import resolve_application_paths


def test_resolve_defaults(tmp_path: Path) -> None:
    """Test that path resolution uses correct default values."""
    paths = resolve_application_paths({"BASE_DIR": tmp_path})
    assert paths.repo_root == tmp_path.resolve()
    assert paths.config_file.name == "app.yml"
