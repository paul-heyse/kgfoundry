"""Utility to apply postponed annotations (PEP 563) to Python modules.

This script automatically inserts `from __future__ import annotations` into
Python modules, ensuring that type hints are no longer evaluated at import time.
It respects module docstrings, encoding declarations, and shebang lines.

## Design

1. Scans targeted directories for .py files
2. Checks if `from __future__ import annotations` is already present
3. If missing, inserts it after:
   - Shebang (#!/usr/bin/env python, etc.)
   - Encoding declaration (# -*- coding: utf-8 -*-)
   - Module docstring (triple-quoted strings at top)
4. Leaves other imports and code untouched
5. Reports summary: files processed, inserted count, errors

## Usage

    # Apply to entire src/ directory
    python -m tools.lint.apply_postponed_annotations src/

    # Apply to specific modules
    python -m tools.lint.apply_postponed_annotations docs/_scripts/ tools/

    # Check without modifying (dry-run)
    python -m tools.lint.apply_postponed_annotations --check-only src/
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence


def should_skip_file(path: Path) -> bool:
    """Determine if a file should be skipped.

    Parameters
    ----------
    path : Path
        File path to check.

    Returns
    -------
    bool
        True if the file should be skipped (hidden or cache directories).
    """
    # Skip __pycache__, .git, .venv, etc.
    if any(part.startswith(".") for part in path.parts):
        return True
    return "pycache" in path.parts


def has_postponed_annotations(content: str) -> bool:
    """Check if file already has postponed annotations import.

    Parameters
    ----------
    content : str
        File content to check.

    Returns
    -------
    bool
        True if the content contains the postponed annotations import.
    """
    return "from __future__ import annotations" in content


def extract_header_and_body(content: str) -> tuple[str, str]:
    """Extract header (shebang, encoding, docstring) from body.

    Parameters
    ----------
    content : str
        File content to parse.

    Returns
    -------
    tuple[str, str]
        (header_section, remaining_body)
    """
    lines = content.split("\n")
    header_lines: list[str] = []
    idx = 0

    # Shebang
    if idx < len(lines) and lines[idx].startswith("#!"):
        header_lines.append(lines[idx])
        idx += 1

    # Encoding declaration
    if idx < len(lines) and ("coding:" in lines[idx] or "coding=" in lines[idx]):
        header_lines.append(lines[idx])
        idx += 1

    # Module docstring: try to parse it
    if idx < len(lines):
        # Build a candidate for docstring extraction
        remaining = "\n".join(lines[idx:])
        try:
            tree = ast.parse(remaining)
            # Check if first statement is a docstring
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                # It's a docstring; extract it by finding closing quote
                docstring_node = tree.body[0]
                # Count lines in docstring
                start_line = docstring_node.lineno or 1
                end_line = docstring_node.end_lineno or start_line
                docstring_lineno = end_line - start_line + 1
                header_lines.extend(lines[idx : idx + docstring_lineno])
                idx += docstring_lineno
        except (SyntaxError, IndexError):
            # If parsing fails, don't assume docstring
            pass

    header = "\n".join(header_lines)
    body = "\n".join(lines[idx:])
    return header, body


def apply_postponed_annotations(content: str) -> str:
    """Insert postponed annotations import if not present.

    Respects shebang, encoding, and module docstring.

    Parameters
    ----------
    content : str
        File content.

    Returns
    -------
    str
        Modified content with postponed annotations inserted.
    """
    if has_postponed_annotations(content):
        return content

    header, body = extract_header_and_body(content)

    # Build the new import statement
    import_line = "from __future__ import annotations\n"

    # Combine: header + import + body
    if header:
        # If header ends with newline, don't add extra
        if header.endswith("\n"):
            return header + import_line + body
        return header + "\n" + import_line + body

    return import_line + body


@dataclass(frozen=True, slots=True)
class RewriteConfig:
    """Configuration describing how a module should be rewritten."""

    path: Path
    check_only: bool
    encoding: str = "utf-8"


@dataclass(frozen=True, slots=True)
class RewritePlan:
    """Plan capturing original and rewritten module contents."""

    config: RewriteConfig
    original: str
    updated: str

    @property
    def has_changes(self) -> bool:
        """Return True when the rewritten content differs from the original."""
        return self.original != self.updated


def _parse_rewrite_config(path: Path, *, check_only: bool) -> RewriteConfig:
    """Create rewrite configuration for ``path``.

    Parameters
    ----------
    path : Path
        File path to configure.
    check_only : bool
        Whether to only check without modifying files.

    Returns
    -------
    RewriteConfig
        Configuration for the rewrite operation.
    """
    return RewriteConfig(path=path, check_only=check_only)


def _update_imports(config: RewriteConfig) -> RewritePlan:
    """Compute rewritten content for the provided configuration.

    Parameters
    ----------
    config : RewriteConfig
        Configuration for the rewrite operation.

    Returns
    -------
    RewritePlan
        Plan containing original and updated content.
    """
    original = config.path.read_text(encoding=config.encoding)
    updated = apply_postponed_annotations(original)
    return RewritePlan(config=config, original=original, updated=updated)


def _write_back(plan: RewritePlan) -> bool:
    """Persist rewritten content when changes are detected.

    Parameters
    ----------
    plan : RewritePlan
        Plan containing changes to persist.

    Returns
    -------
    bool
        True if changes were detected (and written if not check-only).
    """
    if not plan.has_changes:
        return False
    if plan.config.check_only:
        return True
    plan.config.path.write_text(plan.updated, encoding=plan.config.encoding)
    return True


def rewrite_file(path: Path, *, check_only: bool) -> bool:
    """Rewrite a Python file and return True when the content changes.

    Parameters
    ----------
    path : Path
        File path to rewrite.
    check_only : bool
        Whether to only check without modifying files.

    Returns
    -------
    bool
        True if the file content would change (or was changed).
    """
    config = _parse_rewrite_config(path, check_only=check_only)
    plan = _update_imports(config)
    return _write_back(plan)


def _normalize_directories(raw_directories: Sequence[Path]) -> list[Path]:
    """Normalize user-provided directories, defaulting to ``src/``.

    Parameters
    ----------
    raw_directories : Sequence[Path]
        User-provided directory paths.

    Returns
    -------
    list[Path]
        Normalized list of directories, or [Path("src")] if empty.
    """
    return list(raw_directories) if raw_directories else [Path("src")]


def _aggregate_results(
    directories: Sequence[Path],
    *,
    check_only: bool,
) -> tuple[int, int, int]:
    """Process each directory and return aggregate statistics.

    Parameters
    ----------
    directories : Sequence[Path]
        Directories to process.
    check_only : bool
        Whether to only check without modifying files.

    Returns
    -------
    tuple[int, int, int]
        (files_processed, files_modified, errors) statistics.
    """
    total_processed = 0
    total_modified = 0
    total_errors = 0

    for directory in directories:
        if not directory.exists():
            continue
        processed, modified, errors = process_directory(
            directory,
            check_only=check_only,
        )
        total_processed += processed
        total_modified += modified
        total_errors += errors

    return total_processed, total_modified, total_errors


def process_directory(
    root: Path,
    *,
    check_only: bool = False,
) -> tuple[int, int, int]:
    """Process all Python files in a directory.

    Parameters
    ----------
    root : Path
        Root directory to scan.
    check_only : bool, optional
        If True, don't modify files, only report (default: False).

    Returns
    -------
    tuple[int, int, int]
        (files_processed, files_modified, errors)
    """
    processed = 0
    modified = 0
    errors = 0

    py_files = sorted(root.rglob("*.py"))

    for fpath in py_files:
        if should_skip_file(fpath):
            continue

        processed += 1
        try:
            changed = rewrite_file(fpath, check_only=check_only)
            if changed:
                modified += 1
        except (OSError, RuntimeError):
            errors += 1

    return processed, modified, errors


def main(argv: Sequence[str] | None = None) -> int:
    """Apply postponed annotations to specified directories.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments (directories or flags).
        Flags: --check-only, --help

    Returns
    -------
    int
        Exit code (0 = success, non-zero = failure).
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Apply postponed annotations (PEP 563) to Python modules."
    )
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        help="Directories to process (default: src/)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check without modifying files",
    )

    args = parser.parse_args(argv)

    check_attr: object = getattr(args, "check_only", False)
    check_flag = bool(check_attr)

    raw_directories = cast("Sequence[Path]", getattr(args, "directories", ()))
    directories = _normalize_directories(raw_directories)
    _, _, total_errors = _aggregate_results(
        directories,
        check_only=check_flag,
    )

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
