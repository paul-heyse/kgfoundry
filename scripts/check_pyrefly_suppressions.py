#!/usr/bin/env python3
"""Scan for unmanaged pyrefly and type: ignore suppressions.

This script enforces governance over type suppression usage by requiring that all
`# type: ignore` and `# pyrefly: ignore` pragmas include a ticket reference or
documented rationale. Suppressions without justification are flagged as errors.

Exit codes:
    0: No unmanaged suppressions found.
    1: Unmanaged suppressions detected; remediation guidance printed to stderr.
    2: Script error (invalid args, I/O failure).

Examples
--------
>>> # Scan the src/ directory
>>> python scripts/check_pyrefly_suppressions.py src/

>>> # Scan specific file
>>> python scripts/check_pyrefly_suppressions.py src/mymodule.py

>>> # Show help
>>> python scripts/check_pyrefly_suppressions.py --help
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class _ParsedArgs(argparse.Namespace):
    paths: list[Path]
    exit_zero: bool


# Pattern to match unmanaged suppressions: type: ignore or pyrefly: ignore
# without a ticket reference (e.g., "# type: ignore[error-code] - ticket #123")
SUPPRESSION_PATTERN = re.compile(r"#\s*(?:type:\s*ignore|pyrefly:\s*ignore)(?:\[[\w,-]+\])?")
# Pattern to detect a ticket reference in a comment
TICKET_PATTERN = re.compile(r"(?:ticket|issue|#\d+|GH-\d+|TODO)", re.IGNORECASE)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Scan a file for unmanaged suppressions.

    Parameters
    ----------
    path : Path
        Path to the file to scan.

    Returns
    -------
    list[tuple[int, str]]
        List of (line_number, line_content) tuples for unmanaged suppressions.

    Raises
    ------
    ValueError
        If the file cannot be read.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        message = f"Failed to read {path}: {type(exc).__name__}"
        raise ValueError(message) from exc

    unmanaged: list[tuple[int, str]] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        if SUPPRESSION_PATTERN.search(line) and not TICKET_PATTERN.search(line):
            unmanaged.append((line_num, line.rstrip()))

    return unmanaged


@dataclass(frozen=True)
class ScanResult:
    """Summary of scanned files and any unmanaged suppressions discovered."""

    files_scanned: int
    issues: dict[Path, list[tuple[int, str]]]


def _parse_args(argv: Sequence[str] | None) -> _ParsedArgs:
    parser = argparse.ArgumentParser(
        description="Check for unmanaged pyrefly and type: ignore suppressions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Suppressions must include a ticket reference (e.g., # type: ignore[error] - ticket #123)\n"
            "to be recognized as managed.\n\n"
            "Example:\n"
            "  python scripts/check_pyrefly_suppressions.py src/\n"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="File or directory paths to scan",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Exit with code 0 even if suppressions found (dry-run mode)",
    )
    parsed = parser.parse_args(argv)
    return cast("_ParsedArgs", parsed)


def _iter_python_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        if target.suffix == ".py":
            yield target
        return
    yield from sorted(target.rglob("*.py"))


def _scan_targets(paths: Sequence[Path]) -> ScanResult:
    issues: dict[Path, list[tuple[int, str]]] = {}
    files_scanned = 0
    for target in paths:
        resolved = target.resolve()
        if not resolved.exists():
            message = f"path not found: {target}"
            raise FileNotFoundError(message)
        for py_file in _iter_python_files(resolved):
            files_scanned += 1
            try:
                unmanaged = check_file(py_file)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if unmanaged:
                issues[py_file] = unmanaged
    return ScanResult(files_scanned=files_scanned, issues=issues)


def _write_issue_report(issues: dict[Path, list[tuple[int, str]]]) -> None:
    sys.stderr.write(
        f"error: found {len(issues)} files with unmanaged suppressions:\n\n",
    )
    for file_path, entries in issues.items():
        sys.stderr.write(f"{file_path}:\n")
        for line_num, content in entries:
            sys.stderr.write(f"  {line_num:4d}: {content}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        "Remedy: Add a ticket reference to each suppression."
        "\nExample: # type: ignore[misc] - ticket #456\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Scan Python source files for unmanaged type suppressions.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments. If None, sys.argv[1:] is used.

    Returns
    -------
    int
        Exit code: 0 if no issues, 1 if suppressions found, 2 on error.

    Examples
    --------
    >>> # Scan current directory recursively
    >>> exit_code = main(["src/"])
    >>> exit_code
    0
    """
    args = _parse_args(argv)

    try:
        scan_result = _scan_targets(cast("Sequence[Path]", args.paths))
    except FileNotFoundError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if scan_result.issues:
        _write_issue_report(scan_result.issues)
        exit_zero = args.exit_zero
        return 0 if exit_zero else 1

    sys.stdout.write(
        f"✓ All {scan_result.files_scanned} Python files clean (no unmanaged suppressions)\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
