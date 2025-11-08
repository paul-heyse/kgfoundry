"""Shared dataclasses used by the docstring builder pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.builder_types import ExitStatus
    from tools.docstring_builder.docfacts import DocFact
    from tools.docstring_builder.ir import IRDocstring
    from tools.docstring_builder.models import ErrorReport, RunStatus
    from tools.docstring_builder.semantics import SemanticResult


@dataclass(slots=True, frozen=True)
class ProcessingOptions:
    """Runtime options controlling how a file is processed."""

    command: str
    force: bool
    ignore_missing: bool
    missing_patterns: tuple[str, ...]
    skip_docfacts: bool
    baseline: str | None = None


@dataclass(slots=True, frozen=True)
class FileOutcome:
    """Result of processing a single file."""

    status: ExitStatus
    docfacts: list[DocFact]
    preview: str | None
    changed: bool
    skipped: bool
    message: str | None = None
    cache_hit: bool = False
    semantics: list[SemanticResult] = field(default_factory=list)
    ir: list[IRDocstring] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class DocfactsResult:
    """Outcome of reconciling DocFacts artifacts."""

    status: Literal["success", "violation", "config", "error"]
    message: str | None = None
    diff_path: Path | None = None


@dataclass(slots=True, frozen=True)
class ErrorEnvelope:
    """Structured error entry returned by the pipeline."""

    file: str
    status: RunStatus
    message: str

    def to_report(self) -> ErrorReport:
        """Convert the envelope to the ErrorReport mapping.

        Returns
        -------
        ErrorReport
            Error report dictionary with file, status, and message fields.
        """
        return {"file": self.file, "status": self.status, "message": self.message}
