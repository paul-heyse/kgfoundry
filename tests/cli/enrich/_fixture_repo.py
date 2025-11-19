"""Helpers for materializing the completeness CLI fixture repository."""

from __future__ import annotations

from pathlib import Path

FIXTURE_FILES: dict[Path, str] = {
    Path("pkg/__init__.py"): '"""Test fixture package for completeness validation tests."""\n',
    Path("pkg/a.py"): (
        '"""Test fixture module A for completeness validation tests."""\n\n'
        "from pkg import missing\n"
        "from ... import outside\n\n"
        "# Emit references so LibCST captures downstream impact edges.\n"
        "BROKEN_IMPORTS = (outside, missing)\n"
    ),
    Path("pkg/b.py"): '"""Test fixture module B for completeness validation tests."""\n',
    Path("pkg/sub/module.py"): (
        '"""Test fixture submodule for completeness validation tests."""\n\n'
        "VALUE = 1\n"
    ),
}


def write_completeness_fixture_repo(dst: Path) -> Path:
    """Create the completeness audit fixture repository under ``dst``.

    Returns
    -------
    Path
        The destination path containing the generated repository.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for rel_path, contents in FIXTURE_FILES.items():
        target = dst / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return dst


__all__ = ["write_completeness_fixture_repo"]
