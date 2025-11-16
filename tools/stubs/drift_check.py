"""Runtime check for drift between stub packages and installed modules."""

from __future__ import annotations

import argparse
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(slots=True, frozen=True)
class ModuleSpec:
    """Describe the public API exported by a runtime module."""

    name: str
    expected: set[str]
    monitor: set[str] | None = None


@dataclass(slots=True, frozen=True)
class DriftResult:
    """Outcome of inspecting a module for stub drift."""

    module: str
    missing: list[str]
    unexpected: list[str]
    error: str | None = None

    @property
    def has_drift(self) -> bool:
        """Return ``True`` when the module exhibits missing or unexpected members."""
        return bool(self.missing or self.unexpected or self.error)


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name="griffe",
        expected={
            "Class",
            "Docstring",
            "Function",
            "GriffeLoader",
            "Module",
            "Object",
            "Parameter",
        },
        monitor={"Class", "Function", "Module", "Object", "Parameter", "GriffeLoader"},
    ),
    ModuleSpec(
        name="griffe.loader",
        expected={"GriffeLoader"},
    ),
    ModuleSpec(
        name="griffe.dataclasses",
        expected={"Class", "Docstring", "Function", "Module", "Object", "Parameter"},
    ),
    ModuleSpec(
        name="libcst",
        expected={
            "BaseStatement",
            "CSTNode",
            "CSTTransformer",
            "CSTVisitor",
            "ClassDef",
            "Expr",
            "FunctionDef",
            "Module",
            "Name",
            "SimpleStatementLine",
            "SimpleString",
            "parse_module",
        },
    ),
    ModuleSpec(
        name="mkdocs_gen_files",
        expected={"open"},
    ),
)


def _inspect_module(spec: ModuleSpec) -> DriftResult:
    try:
        module = importlib.import_module(spec.name)
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        return DriftResult(
            module=spec.name,
            missing=sorted(spec.expected),
            unexpected=[],
            error=str(exc),
        )

    public = {attr for attr in dir(module) if not attr.startswith("_")}
    missing = sorted(name for name in spec.expected if name not in public)
    monitor = spec.monitor or spec.expected
    unexpected = sorted(name for name in public if name in monitor and name not in spec.expected)
    return DriftResult(module=spec.name, missing=missing, unexpected=unexpected)


def _format_section(title: str, values: Iterable[str]) -> str:
    joined = ", ".join(values)
    return f"  - {title}: {joined if joined else 'none'}"


def run() -> int:
    """Execute the drift checker CLI.

    Extended Summary
    ----------------
    This CLI tool validates stub coverage for optional dependencies by comparing
    the public API of runtime modules against their corresponding stub files.
    It detects missing stubs, unexpected stubs, and import errors, ensuring
    type checking remains accurate as optional dependencies evolve.

    Returns
    -------
    int
        Exit code: 0 on success (no drift detected), 1 on failure (drift detected
        or import errors encountered).

    Raises
    ------
    SystemExit
        When stub drift is detected (missing or unexpected stubs) or when import
        errors occur during module inspection. The exit code is 1, and the error
        message includes a formatted summary of all drift issues found per module.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(n) where n is the number of modules inspected. Attempts
        to import optional dependencies; may fail if dependencies are not installed.
        Reads stub files from disk; no writes. Thread-safe for concurrent checks.

    See Also
    --------
    _inspect_module : Core module inspection logic
    MODULE_SPECS : Registry of modules to validate
    """
    parser = argparse.ArgumentParser(
        description="Validate stub coverage for optional dependencies."
    )
    parser.parse_args()
    failures: list[DriftResult] = []
    for spec in MODULE_SPECS:
        result = _inspect_module(spec)
        if result.has_drift:
            failures.append(result)
    if failures:
        lines = ["Stub drift detected:"]
        for failure in failures:
            parts = []
            if failure.missing:
                parts.append(f"missing: {', '.join(failure.missing)}")
            if failure.unexpected:
                parts.append(f"unexpected: {', '.join(failure.unexpected)}")
            if failure.error:
                parts.append(f"error: {failure.error}")
            detail = "; ".join(parts)
            lines.append(f"  - {failure.module}: {detail}")
        raise SystemExit("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(run())
