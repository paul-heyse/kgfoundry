#!/usr/bin/env python3
"""Check for new type ignores and noqa directives without TICKET: tags.

This script scans source files for new `# type-ignore` or `# noqa` directives
that don't include a `TICKET:` tag. It fails the build if untracked suppressions
are found, enforcing zero-tolerance for unmanaged suppressions.

Examples
--------
>>> python tools/check_new_suppressions.py src
# Exits 0 if all suppressions have TICKET: tags
# Exits 1 with detailed output if untracked suppressions found
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, TypedDict, cast

from kgfoundry_common.errors import ConfigurationError
from tools._shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

LOGGER = get_logger(__name__)

# Public exports for static type checkers and consumers.
__all__ = (
    "SuppressionGuardContext",
    "SuppressionGuardFileEntry",
    "SuppressionGuardFileReport",
    "SuppressionGuardReport",
    "SuppressionGuardViolationEntry",
    "SuppressionViolation",
    "build_guard_context",
    "check_directory",
    "check_file",
    "main",
    "resolve_target_directories",
    "run_suppression_guard",
)

# Regex patterns for suppression markers and ticket tags within a comment token.
SUPPRESSION_MARKER = re.compile(
    r"#\s*(?:type\s*:\s*ignore|noqa(?:\s*[:\s][\w,]+)?)",
    re.IGNORECASE,
)
TICKET_PATTERN = re.compile(r"#\s*TICKET:\s*\S+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SuppressionViolation:
    """Record representing a suppression comment missing a ``TICKET:`` tag."""

    path: Path
    line_number: int
    line_preview: str


class SuppressionGuardViolationEntry(TypedDict):
    """Payload describing a single suppression violation."""

    line: int
    preview: str


class SuppressionGuardFileEntry(TypedDict):
    """Collection of violations for a particular file."""

    file: str
    violations: list[SuppressionGuardViolationEntry]


class SuppressionGuardContext(TypedDict):
    """Problem Details context for suppression guard failures."""

    violation_count: int
    files: list[SuppressionGuardFileEntry]


@dataclass(frozen=True, slots=True)
class SuppressionGuardReport:
    """Aggregate results for a suppression guard run."""

    files: tuple[SuppressionGuardFileReport, ...]

    def __post_init__(self) -> None:
        """Validate report invariants and normalize internal state."""
        object.__setattr__(self, "files", _normalize_file_reports(self.files))

    @property
    def violations(self) -> Mapping[Path, tuple[SuppressionViolation, ...]]:
        """Expose violations keyed by path for backwards compatibility."""
        mapping = {file_report.path: file_report.violations for file_report in self.files}
        proxy = MappingProxyType(mapping)
        return cast("Mapping[Path, tuple[SuppressionViolation, ...]]", proxy)

    @property
    def violation_count(self) -> int:
        """Return the total number of violations discovered."""
        return sum(len(report.violations) for report in self.files)

    @property
    def is_clean(self) -> bool:
        """Return ``True`` when the report has no violations.

        Returns
        -------
        bool
            True if no violations found.
        """
        return self.violation_count == 0

    def to_context(self) -> SuppressionGuardContext:
        """Render the report as structured problem details context.

        Returns
        -------
        SuppressionGuardContext
            Problem Details context dictionary.
        """
        return build_guard_context(self)

    @classmethod
    def merge(cls, reports: Iterable[SuppressionGuardReport]) -> SuppressionGuardReport:
        """Merge multiple reports into a single aggregate.

        Parameters
        ----------
        reports : Iterable[SuppressionGuardReport]
            Reports to merge.

        Returns
        -------
        SuppressionGuardReport
            Merged report.
        """
        aggregated: dict[Path, list[SuppressionViolation]] = {}
        for report in reports:
            for file_report in report.files:
                bucket = aggregated.setdefault(file_report.path, [])
                bucket.extend(file_report.violations)

        normalized_files = tuple(
            SuppressionGuardFileReport(path=path, violations=tuple(violations))
            for path, violations in aggregated.items()
        )
        return cls(files=normalized_files)

    @classmethod
    def from_context(cls, context: SuppressionGuardContext) -> SuppressionGuardReport:
        """Build a report instance from a context payload.

        Parameters
        ----------
        context : SuppressionGuardContext
            Problem Details context dictionary.

        Returns
        -------
        SuppressionGuardReport
            Report instance.

        Raises
        ------
        ValueError
            If violation count mismatch is detected.
        """
        files = tuple(
            SuppressionGuardFileReport.from_context_entry(entry) for entry in context["files"]
        )

        report = cls(files=files)
        expected_count = context["violation_count"]
        if report.violation_count != expected_count:
            message = (
                "Suppression guard context mismatch: "
                f"expected {expected_count} violations, "
                f"computed {report.violation_count}."
            )
            raise ValueError(message)
        return report


@dataclass(frozen=True, slots=True)
class SuppressionGuardFileReport:
    """Collection of violations for a specific file."""

    path: Path
    violations: tuple[SuppressionViolation, ...]

    def __post_init__(self) -> None:
        """Normalize violation ordering for deterministic comparisons."""
        object.__setattr__(self, "violations", _normalize_violations(self.violations))

    def to_context_entry(self) -> SuppressionGuardFileEntry:
        """Return a serializable representation for Problem Details.

        Returns
        -------
        SuppressionGuardFileEntry
            Problem Details file entry dictionary.
        """
        return {
            "file": str(self.path),
            "violations": [
                {
                    "line": violation.line_number,
                    "preview": violation.line_preview,
                }
                for violation in self.violations
            ],
        }

    @classmethod
    def from_context_entry(cls, entry: SuppressionGuardFileEntry) -> SuppressionGuardFileReport:
        """Hydrate a file report from its Problem Details entry.

        Parameters
        ----------
        entry : SuppressionGuardFileEntry
            Problem Details file entry dictionary.

        Returns
        -------
        SuppressionGuardFileReport
            File report instance.
        """
        path = Path(entry["file"]).resolve()
        violations = tuple(
            SuppressionViolation(
                path=path,
                line_number=item["line"],
                line_preview=item["preview"],
            )
            for item in entry["violations"]
        )
        return cls(path=path, violations=violations)


def _guard_file_sort_key(report: SuppressionGuardFileReport) -> str:
    """Return a deterministic sort key for file reports.

    Parameters
    ----------
    report : SuppressionGuardFileReport
        File report.

    Returns
    -------
    str
        Sort key string.
    """
    return report.path.as_posix()


def _violation_sort_key(violation: SuppressionViolation) -> int:
    """Return a deterministic sort key for individual violations.

    Parameters
    ----------
    violation : SuppressionViolation
        Violation instance.

    Returns
    -------
    int
        Line number sort key.
    """
    return violation.line_number


def _normalize_file_reports(
    files: Iterable[SuppressionGuardFileReport],
) -> tuple[SuppressionGuardFileReport, ...]:
    """Return files sorted by path for deterministic behavior.

    Parameters
    ----------
    files : Iterable[SuppressionGuardFileReport]
        File reports to normalize.

    Returns
    -------
    tuple[SuppressionGuardFileReport, ...]
        Sorted tuple of file reports.
    """
    return tuple(sorted(files, key=_guard_file_sort_key))


def _normalize_violations(
    violations: Iterable[SuppressionViolation],
) -> tuple[SuppressionViolation, ...]:
    """Return violations sorted by ascending line number.

    Parameters
    ----------
    violations : Iterable[SuppressionViolation]
        Violations to normalize.

    Returns
    -------
    tuple[SuppressionViolation, ...]
        Sorted tuple of violations.
    """
    return tuple(sorted(violations, key=_violation_sort_key))


def _iter_suppression_comments(content: str) -> Sequence[tuple[int, str]]:
    """Yield ``(line_number, comment)`` pairs for suppression comments.

    Parameters
    ----------
    content : str
        Source file content.

    Returns
    -------
    Sequence[tuple[int, str]]
        List of (line_number, comment) tuples.
    """
    reader = io.StringIO(content).readline
    matches: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(reader):
        if token.type != tokenize.COMMENT:
            continue
        comment = token.string
        if SUPPRESSION_MARKER.search(comment):
            matches.append((token.start[0], comment))
    return tuple(matches)


def check_file(file_path: Path) -> tuple[SuppressionViolation, ...]:
    """Return suppressions lacking ``TICKET:`` metadata within ``file_path``.

    Parameters
    ----------
    file_path : Path
        File path to check.

    Returns
    -------
    tuple[SuppressionViolation, ...]
        Tuple of violations found.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.warning("Could not read %s", file_path, exc_info=exc)
        return ()

    lines = content.splitlines()
    violations: list[SuppressionViolation] = []

    for line_number, comment in _iter_suppression_comments(content):
        if TICKET_PATTERN.search(comment):
            continue

        preview = lines[line_number - 1].strip() if 0 < line_number <= len(lines) else ""
        violations.append(
            SuppressionViolation(path=file_path, line_number=line_number, line_preview=preview)
        )

    return tuple(violations)


def check_directory(directory: Path) -> SuppressionGuardReport:
    """Return per-file suppressions lacking ``TICKET:`` metadata.

    Parameters
    ----------
    directory : Path
        Directory path to check.

    Returns
    -------
    SuppressionGuardReport
        Report with violations found.
    """
    files = tuple(
        SuppressionGuardFileReport(path=py_file.resolve(), violations=file_violations)
        for py_file in sorted(directory.rglob("*.py"))
        if (file_violations := check_file(py_file))
    )

    return SuppressionGuardReport(files=files)


def resolve_target_directories(paths: Sequence[str]) -> list[Path]:
    """Resolve and validate target directories.

    Parameters
    ----------
    paths : Sequence[str]
        List of directory paths to resolve.

    Returns
    -------
    list[Path]
        List of resolved Path objects.

    Raises
    ------
    ConfigurationError
        If any path doesn't exist or is not a directory.
    """
    resolved: list[Path] = []
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            msg = f"Directory does not exist: {path_str}"
            raise ConfigurationError(msg)
        if not path.is_dir():
            msg = f"Path is not a directory: {path_str}"
            raise ConfigurationError(msg)
        resolved.append(path.resolve())
    return resolved


def run_suppression_guard(directories: Sequence[Path]) -> SuppressionGuardReport:
    """Run suppression guard on the given directories.

    Parameters
    ----------
    directories : Sequence[Path]
        Directories to check.

    Returns
    -------
    SuppressionGuardReport
        Final merged report.

    Raises
    ------
    ConfigurationError
        If suppressions without TICKET tags are found.
    """
    reports = [check_directory(directory) for directory in directories]
    final_report = SuppressionGuardReport.merge(reports)

    if not final_report.is_clean:
        message = f"Found {final_report.violation_count} suppression(s) without TICKET: tags"
        raise ConfigurationError(message, context=final_report.to_context())

    return final_report


def build_guard_context(report: SuppressionGuardReport) -> SuppressionGuardContext:
    """Construct structured context payload for Problem Details reporting.

    Parameters
    ----------
    report : SuppressionGuardReport
        Report to convert.

    Returns
    -------
    SuppressionGuardContext
        Problem Details context dictionary.
    """
    files = [file_report.to_context_entry() for file_report in report.files]

    return {"violation_count": report.violation_count, "files": files}


def _extract_guard_report(error: ConfigurationError) -> SuppressionGuardReport | None:
    """Normalize the context payload attached to a suppression guard error.

    Parameters
    ----------
    error : ConfigurationError
        Error with context payload.

    Returns
    -------
    SuppressionGuardReport | None
        Extracted report | None if parsing fails.
    """
    try:
        context = cast("SuppressionGuardContext", dict(error.context))
        return SuppressionGuardReport.from_context(context)
    except (KeyError, TypeError, ValueError):
        LOGGER.exception("Failed to parse suppression guard context")
        return None


def main(argv: Sequence[str] | None = None) -> int:
    """Check source files for untracked suppressions.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments (None uses sys.argv).

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    arguments = list(argv if argv is not None else sys.argv[1:])
    if not arguments:
        LOGGER.error("Usage: python tools/check_new_suppressions.py <directories...>")
        return 1

    try:
        directories = resolve_target_directories(arguments)
    except ConfigurationError:
        LOGGER.exception("Failed to resolve suppression guard target directories")
        return 1

    try:
        run_suppression_guard(directories)
    except ConfigurationError as error:
        report = _extract_guard_report(error)
        if report is None:
            LOGGER.exception("❌ Found suppressions without TICKET: tags")
            return 1
    else:
        LOGGER.info("✅ All suppressions include TICKET: tags")
        return 0

    LOGGER.error(
        "❌ Found suppressions without TICKET: tags",
        extra={"violation_count": report.violation_count},
    )

    cwd = Path.cwd()
    for file_report in report.files:
        file_path = file_report.path
        try:
            rel_path = file_path.relative_to(cwd)
        except ValueError:
            rel_path = file_path
        LOGGER.error("%s:", rel_path, extra={"path": str(rel_path)})
        for violation in file_report.violations:
            LOGGER.error(
                "  Line %s: %s",
                violation.line_number,
                violation.line_preview,
                extra={
                    "path": str(rel_path),
                    "line": violation.line_number,
                    "line_preview": violation.line_preview,
                },
            )

    LOGGER.error("Fix: Add TICKET: <ticket-id> to each suppression line.")
    LOGGER.error("Example: # type-ignore[misc]  # TICKET: ABC-123  # numpy dtype contains Any")
    return 1


if __name__ == "__main__":
    sys.exit(main())
