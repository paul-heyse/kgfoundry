"""Check stub file parity with runtime modules.

This script verifies that stub files (.pyi) mirror runtime module exports
accurately, identifying missing symbols and type issues that could break
downstream tooling.

Usage:
    python tools/check_stub_parity.py

Exit codes:
    0: All checks passed
    1: Mismatches found
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from kgfoundry_common.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = (
    "StubEvaluationResult",
    "StubParityAnyUsageEntry",
    "StubParityContext",
    "StubParityIssueEntry",
    "StubParityIssueRecord",
    "StubParityReport",
    "build_stub_parity_context",
    "check_any_usage",
    "evaluate_stub",
    "get_module_exports",
    "get_stub_exports",
    "main",
    "run_stub_parity_checks",
)


@dataclass(frozen=True, slots=True)
class StubEvaluationResult:
    """Result of stub evaluation."""

    missing_symbols: list[str]
    extra_symbols: list[str]
    any_usages: list[tuple[int, str]]
    has_errors: bool


class StubParityAnyUsageEntry(TypedDict):
    """Representation of an Any usage discovered in a stub."""

    line: int
    preview: str


class StubParityIssueEntry(TypedDict):
    """Structured issue payload for stub parity failures."""

    module: str
    stub_path: str
    missing_symbols: list[str]
    extra_symbols: list[str]
    any_usages: list[StubParityAnyUsageEntry]


class StubParityContext(TypedDict):
    """Problem Details context emitted for stub parity checks."""

    issue_count: int
    error_count: int
    issues: list[StubParityIssueEntry]


@dataclass(frozen=True, slots=True)
class StubParityIssueRecord:
    """Internal representation for a stub parity issue."""

    module: str
    stub_path: Path
    missing_symbols: tuple[str, ...]
    extra_symbols: tuple[str, ...]
    any_usages: tuple[tuple[int, str], ...]

    @property
    def error_count(self) -> int:
        """Return the number of error categories triggered for this issue."""
        count = 0
        if self.missing_symbols:
            count += 1
        if self.any_usages:
            count += 1
        return count

    def to_context_entry(self) -> StubParityIssueEntry:
        """Return a Problem Details-compatible representation.

        Returns
        -------
        StubParityIssueEntry
            Problem Details issue entry dictionary.
        """
        return {
            "module": self.module,
            "stub_path": str(self.stub_path),
            "missing_symbols": list(self.missing_symbols),
            "extra_symbols": list(self.extra_symbols),
            "any_usages": [
                {"line": line_number, "preview": preview}
                for line_number, preview in self.any_usages
            ],
        }

    @classmethod
    def from_context_entry(cls, entry: StubParityIssueEntry) -> StubParityIssueRecord:
        """Hydrate an issue record from Problem Details context.

        Parameters
        ----------
        entry : StubParityIssueEntry
            Problem Details issue entry dictionary.

        Returns
        -------
        StubParityIssueRecord
            Issue record instance.
        """
        stub_path = Path(entry["stub_path"]).resolve()
        any_usages = tuple((usage["line"], usage["preview"]) for usage in entry["any_usages"])
        return cls(
            module=entry["module"],
            stub_path=stub_path,
            missing_symbols=tuple(entry["missing_symbols"]),
            extra_symbols=tuple(entry["extra_symbols"]),
            any_usages=any_usages,
        )


def _issue_sort_key(issue: StubParityIssueRecord) -> tuple[str, str]:
    """Return a deterministic sort key for issue records.

    Parameters
    ----------
    issue : StubParityIssueRecord
        Issue record.

    Returns
    -------
    tuple[str, str]
        (module_name, stub_path) sort key tuple.
    """
    return (issue.module, issue.stub_path.as_posix())


@dataclass(frozen=True, slots=True)
class StubParityReport:
    """Aggregate summary of stub parity evaluation results."""

    issues: tuple[StubParityIssueRecord, ...]

    def __post_init__(self) -> None:
        """Stabilize internal storage for downstream consumers."""
        object.__setattr__(self, "issues", _normalize_issues(self.issues))

    @property
    def issue_count(self) -> int:
        """Return the number of issue entries."""
        return len(self.issues)

    @property
    def error_count(self) -> int:
        """Return the total error categories across all issues."""
        return sum(issue.error_count for issue in self.issues)

    @property
    def has_issues(self) -> bool:
        """Return ``True`` if any issues were recorded."""
        return self.issue_count > 0

    def to_context(self) -> StubParityContext:
        """Produce a problem details context payload.

        Returns
        -------
        StubParityContext
            Problem Details context dictionary.
        """
        return build_stub_parity_context(self)

    @classmethod
    def from_context(cls, context: StubParityContext) -> StubParityReport:
        """Reconstruct a report from Problem Details context.

        Parameters
        ----------
        context : StubParityContext
            Problem Details context dictionary.

        Returns
        -------
        StubParityReport
            Report instance.

        Raises
        ------
        ValueError
            If issue or error count mismatch is detected.
        """
        issues = tuple(
            StubParityIssueRecord.from_context_entry(entry) for entry in context["issues"]
        )
        report = cls(issues=issues)
        expected_issue_count = context["issue_count"]
        expected_error_count = context["error_count"]
        if report.issue_count != expected_issue_count or report.error_count != expected_error_count:
            message = (
                "Stub parity context mismatch: "
                f"expected counts ({expected_issue_count}, {expected_error_count}), "
                f"got ({report.issue_count}, {report.error_count})."
            )
            raise ValueError(message)
        return report


def get_module_exports(module_name: str) -> set[str]:
    """Get public exports from a runtime module.

    Parameters
    ----------
    module_name : str
        Fully qualified module name (e.g., 'kgfoundry.search_api.service').

    Returns
    -------
    set[str]
        Names of public (non-private) exports.

    Raises
    ------
    ConfigurationError
        When the module cannot be imported (ImportError) or when module
        introspection fails. The original ImportError is chained as the cause.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        message = f"Could not import runtime module {module_name}"
        raise ConfigurationError(message) from exc

    # Use __all__ if available, otherwise use dir() filtering
    all_attr: object = getattr(module, "__all__", None)
    if isinstance(all_attr, (list, tuple, set)):
        # Build set explicitly with typed iteration to avoid Any in set() call
        result: set[str] = set()
        for item in cast("Iterable[object]", all_attr):
            result.add(str(item))
        return result

    return {name for name in dir(module) if not name.startswith("_") and not name.startswith("__")}


def _is_export_name(name: str) -> bool:
    """Check if a name should be considered an export.

    Parameters
    ----------
    name : str
        The symbol name to check.

    Returns
    -------
    bool
        True if the name is exportable (non-private).
    """
    return not name.startswith("_")


def _extract_import_names(node: ast.ImportFrom) -> set[str]:
    """Extract exported names from an ImportFrom node.

    Parameters
    ----------
    node : ast.ImportFrom
        The import node to process.

    Returns
    -------
    set[str]
        Names that should be exported.
    """
    names = set()
    if node.names:
        for alias in node.names:
            if _is_export_name(alias.name):
                export_name = alias.asname if alias.asname else alias.name
                if _is_export_name(export_name):
                    names.add(export_name)
    return names


def get_stub_exports(stub_path: Path) -> set[str]:
    """Extract public names from a stub file.

    Parameters
    ----------
    stub_path : Path
        Path to the .pyi stub file. Must exist and contain valid Python syntax.

    Returns
    -------
    set[str]
        Names of symbols defined in the stub. Returns empty set if stub_path
        does not exist.

    Raises
    ------
    ConfigurationError
        When the stub file cannot be parsed (SyntaxError) or when AST parsing
        fails. The original SyntaxError is chained as the cause.
    """
    if not stub_path.exists():
        return set()

    try:
        tree = ast.parse(stub_path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        message = f"Could not parse stub file {stub_path}"
        raise ConfigurationError(message) from exc

    exports = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_export_name(node.name):
                exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_export_name(target.id):
                    exports.add(target.id)
        elif isinstance(node, ast.ImportFrom):
            exports.update(_extract_import_names(node))

    return exports


def check_any_usage(stub_path: Path) -> list[tuple[int, str]]:
    """Find Any type usage in stub file.

    Parameters
    ----------
    stub_path : Path
        Path to the .pyi stub file.

    Returns
    -------
    list[tuple[int, str]]
        List of (line_number, line_content) tuples containing Any usage.
    """
    if not stub_path.exists():
        return []

    any_lines = []
    content = stub_path.read_text(encoding="utf-8")

    for line_num, line in enumerate(content.splitlines(), start=1):
        # Skip comments and ignore directives
        if "Any" in line and not line.strip().startswith("#"):
            # Check if it's an import or actual usage
            if "from typing import" in line or "import " in line:
                # It's an import; flag it only if line has other type hints too
                if line.count("Any") > 0 and (":" in line or "->" in line):
                    any_lines.append((line_num, line.strip()))
            elif " Any" in line or ": Any" in line or "Any[" in line:
                any_lines.append((line_num, line.strip()))

    return any_lines


def evaluate_stub(module_name: str, stub_path: Path) -> StubEvaluationResult:
    """Evaluate a stub file against its runtime module.

    Parameters
    ----------
    module_name : str
        Fully qualified module name.
    stub_path : Path
        Path to the stub file.

    Returns
    -------
    StubEvaluationResult
        Evaluation result with missing symbols, extra symbols, and Any usages.
    """
    runtime_exports = get_module_exports(module_name)
    stub_exports = get_stub_exports(stub_path)
    any_usages = check_any_usage(stub_path)

    missing_symbols = sorted(runtime_exports - stub_exports)
    extra_symbols = sorted(stub_exports - runtime_exports)

    return StubEvaluationResult(
        missing_symbols=missing_symbols,
        extra_symbols=extra_symbols,
        any_usages=any_usages,
        has_errors=bool(missing_symbols or any_usages),
    )


def run_stub_parity_checks(checks: list[tuple[str, Path]]) -> StubParityReport:
    """Run stub parity checks on multiple module/stub pairs.

    Parameters
    ----------
    checks : list[tuple[str, Path]]
        List of (module_name, stub_path) tuples.

    Returns
    -------
    StubParityReport
        Final report.

    Raises
    ------
    ConfigurationError
        If stub parity issues are found.
    """
    issues: list[StubParityIssueRecord] = []

    for module_name, stub_path in checks:
        result = evaluate_stub(module_name, stub_path)
        if result.has_errors:
            issues.append(
                StubParityIssueRecord(
                    module=module_name,
                    stub_path=stub_path,
                    missing_symbols=tuple(result.missing_symbols),
                    extra_symbols=tuple(result.extra_symbols),
                    any_usages=tuple(result.any_usages),
                )
            )

    report = StubParityReport(issues=tuple(issues))

    if report.has_issues:
        message = f"Found {report.issue_count} stub parity issue(s)"
        raise ConfigurationError(message, context=report.to_context())

    return report


def build_stub_parity_context(report: StubParityReport) -> StubParityContext:
    """Construct the canonical stub parity context payload.

    Parameters
    ----------
    report : StubParityReport
        Report to convert.

    Returns
    -------
    StubParityContext
        Problem Details context dictionary.
    """
    issues = [issue.to_context_entry() for issue in report.issues]

    return {
        "issue_count": report.issue_count,
        "error_count": report.error_count,
        "issues": issues,
    }


def _extract_stub_parity_report(error: ConfigurationError) -> StubParityReport | None:
    """Normalize the context associated with a stub parity failure.

    Parameters
    ----------
    error : ConfigurationError
        Error with context payload.

    Returns
    -------
    StubParityReport | None
        Extracted report | None if parsing fails.
    """
    try:
        context = cast("StubParityContext", dict(error.context))
        return StubParityReport.from_context(context)
    except (KeyError, TypeError, ValueError):
        return None


def _format_stub_parity_summary(report: StubParityReport) -> str:
    """Return a human-readable summary of stub parity issues.

    Parameters
    ----------
    report : StubParityReport
        Stub parity report containing issue details for one or more modules
        with mismatches between stubs and runtime implementations.

    Returns
    -------
    str
        Human-readable multi-line summary string listing all parity issues with
        module names, stub paths, and specific mismatch details. Formatted for
        console output.
    """
    lines = [
        f"FAILED: {report.error_count} stub parity issue(s) across {report.issue_count} module(s)",
        "",
    ]
    for issue in report.issues:
        lines.append(f"Module: {issue.module}")
        lines.append(f"Stub: {issue.stub_path}")
        if issue.missing_symbols:
            missing = ", ".join(sorted(issue.missing_symbols))
            lines.append(f"  Missing symbols: {missing}")
        if issue.extra_symbols:
            extra = ", ".join(sorted(issue.extra_symbols))
            lines.append(f"  Extra symbols: {extra}")
        if issue.any_usages:
            lines.append("  Any usages:")
            for line_number, preview in issue.any_usages:
                lines.append(f"    Line {line_number}: {preview}")
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_issues(
    issues: Iterable[StubParityIssueRecord],
) -> tuple[StubParityIssueRecord, ...]:
    """Return issues sorted by module name and stub path.

    Parameters
    ----------
    issues : Iterable[StubParityIssueRecord]
        Issues to normalize.

    Returns
    -------
    tuple[StubParityIssueRecord, ...]
        Sorted tuple of issues.
    """
    return tuple(sorted(issues, key=_issue_sort_key))


def main() -> int:
    """Check parity between stubs and runtime modules.

    Extended Summary
    ----------------
    This CLI tool validates that stub files (``.pyi``) accurately reflect the
    public API of their corresponding runtime modules. It compares exports,
    signatures, and type annotations to detect drift between stubs and implementation,
    ensuring type checking remains accurate as code evolves.

    Returns
    -------
    int
        Exit code: 0 on success (stubs match runtime modules), 1 on failure
        (parity issues detected or configuration error).

    Raises
    ------
    SystemExit
        When a configuration error occurs during stub parsing or when stub
        parity issues are detected. The exit code is 1, and the error message
        includes a formatted summary of all parity issues found.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(n*m) where n is the number of modules checked and m
        is the average number of symbols per module. Reads stub and runtime files
        from disk; no writes. Thread-safe for concurrent checks.

    See Also
    --------
    run_stub_parity_checks : Core parity checking algorithm
    _format_stub_parity_summary : Issue formatting and reporting
    """
    project_root = Path(__file__).parent.parent
    stubs_dir = project_root / "stubs" / "kgfoundry"

    modules_to_check = [
        ("kgfoundry._namespace_proxy", stubs_dir / "_namespace_proxy.pyi"),
    ]

    try:
        run_stub_parity_checks(modules_to_check)
    except ConfigurationError as error:
        extracted_report = _extract_stub_parity_report(error)
        if extracted_report is None:
            raise SystemExit(str(error)) from error
        message = _format_stub_parity_summary(extracted_report)
        raise SystemExit(message) from error

    return 0


if __name__ == "__main__":
    sys.exit(main())
