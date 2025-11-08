"""Runtime check for drift between stub packages and installed modules."""

from __future__ import annotations

import argparse
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tools import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

LOGGER = get_logger(__name__)


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
            module=spec.name, missing=sorted(spec.expected), unexpected=[], error=str(exc)
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

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="Validate stub coverage for optional dependencies."
    )
    parser.parse_args()
    failures: list[DriftResult] = []
    for spec in MODULE_SPECS:
        result = _inspect_module(spec)
        if result.error:
            LOGGER.error("[ERROR] %s: %s", spec.name, result.error)
        else:
            LOGGER.info("[INFO] %s", spec.name)
            LOGGER.info(_format_section("missing", result.missing))
            LOGGER.info(_format_section("unexpected", result.unexpected))
        if result.has_drift:
            failures.append(result)
    if failures:
        LOGGER.error("Stub drift detected:")
        for failure in failures:
            parts = []
            if failure.missing:
                parts.append(f"missing: {', '.join(failure.missing)}")
            if failure.unexpected:
                parts.append(f"unexpected: {', '.join(failure.unexpected)}")
            if failure.error:
                parts.append(f"error: {failure.error}")
            detail = "; ".join(parts)
            LOGGER.error("  - %s: %s", failure.module, detail)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(run())
