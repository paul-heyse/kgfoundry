"""Core types and helpers for the docstring builder pipeline.

This module centralises the shared dataclasses and enums that describe the docstring builder
request/response lifecycle.  Keeping these definitions in a single location prevents circular
imports between orchestration helpers and the CLI entry points while providing typed utilities for
status conversion and Problem Details emission.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from kgfoundry_common.logging import LoggerAdapter
from tools._shared.problem_details import (
    ProblemDetailsParams,
)
from tools._shared.problem_details import (
    build_problem_details as _build_problem_details,
)
from tools.docstring_builder.models import (
    RunStatus,
    StatusCounts,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from tools._shared.augment_registry import ToolingMetadataModel
    from tools.docstring_builder.config import ConfigSelection
    from tools.docstring_builder.models import (
        CliResult,
        ErrorReport,
        FileReport,
    )
    from tools.docstring_builder.models import (
        ProblemDetails as ModelProblemDetails,
    )

type LoggerLike = LoggerAdapter | logging.Logger
"""Type alias for logger parameters: accepts both StructuredLoggerAdapter and stdlib Logger."""


class ExitStatus(enum.IntEnum):
    """Standardised exit codes for CLI subcommands."""

    SUCCESS = 0
    VIOLATION = 1
    CONFIG = 2
    ERROR = 3


STATUS_LABELS: dict[ExitStatus, str] = {
    ExitStatus.SUCCESS: "success",
    ExitStatus.VIOLATION: "violation",
    ExitStatus.CONFIG: "config",
    ExitStatus.ERROR: "error",
}


EXIT_SUCCESS = int(ExitStatus.SUCCESS)
EXIT_VIOLATION = int(ExitStatus.VIOLATION)
EXIT_CONFIG = int(ExitStatus.CONFIG)
EXIT_ERROR = int(ExitStatus.ERROR)

_EXIT_TO_RUN_STATUS: dict[ExitStatus, RunStatus] = {
    ExitStatus.SUCCESS: RunStatus.SUCCESS,
    ExitStatus.VIOLATION: RunStatus.VIOLATION,
    ExitStatus.CONFIG: RunStatus.CONFIG,
    ExitStatus.ERROR: RunStatus.ERROR,
}


def status_from_exit(status: ExitStatus) -> RunStatus:
    """Translate an :class:`ExitStatus` into the CLI ``RunStatus`` enum.

    Parameters
    ----------
    status : ExitStatus
        Exit status to translate.

    Returns
    -------
    RunStatus
        Corresponding run status, or ``RunStatus.ERROR`` if status is unknown.
    """
    return _EXIT_TO_RUN_STATUS.get(status, RunStatus.ERROR)


def status_from_label(label: str) -> RunStatus:
    """Translate a status label string into ``RunStatus``.

    Parameters
    ----------
    label : str
        Status label string (case-insensitive).

    Returns
    -------
    RunStatus
        Corresponding run status, or ``RunStatus.ERROR`` if label is unrecognized.
    """
    lowered = label.lower()
    match lowered:
        case "success":
            return RunStatus.SUCCESS
        case "violation" | "warn" | "autofix":
            return RunStatus.VIOLATION
        case "config":
            return RunStatus.CONFIG
        case "error":
            return RunStatus.ERROR
        case _:
            return RunStatus.ERROR


def http_status_for_exit(status: ExitStatus) -> int:
    """Map an :class:`ExitStatus` to an HTTP Problem Details status.

    Parameters
    ----------
    status : ExitStatus
        Exit status to map.

    Returns
    -------
    int
        HTTP status code (200 for SUCCESS, 422 for VIOLATION, 400 for CONFIG, 500 for ERROR).

    Raises
    ------
    AssertionError
        If the status is not one of the known ExitStatus values.
    """
    match status:
        case ExitStatus.SUCCESS:
            return 200
        case ExitStatus.VIOLATION:
            return 422
        case ExitStatus.CONFIG:
            return 400
        case ExitStatus.ERROR:
            return 500
    raise AssertionError(status)


@dataclass(slots=True, frozen=True)
class DocstringBuildRequest:
    """Typed request describing a docstring builder run."""

    command: str
    subcommand: str
    module: str | None = None
    since: str | None = None
    changed_only: bool = False
    explicit_paths: tuple[str, ...] = ()
    force: bool = False
    diff: bool = False
    ignore_missing: bool = False
    skip_docfacts: bool = False
    json_output: bool = False
    jobs: int = 1
    baseline: str | None = None
    only_plugins: tuple[str, ...] = ()
    disable_plugins: tuple[str, ...] = ()
    policy_overrides: Mapping[str, str] = field(default_factory=dict)
    llm_summary: bool = False
    llm_dry_run: bool = False
    normalize_sections: bool = False
    invoked_subcommand: str | None = None


@dataclass(slots=True, frozen=True)
class DocstringBuildResult:
    """Structured result produced by a docstring builder run."""

    exit_status: ExitStatus
    errors: list[ErrorReport]
    file_reports: list[FileReport]
    observability_payload: Mapping[str, object]
    cli_payload: CliResult | None
    manifest_path: Path | None
    problem_details: ModelProblemDetails | None
    config_selection: ConfigSelection | None
    diff_previews: list[tuple[Path, str]] = field(default_factory=list)
    tooling_metadata: ToolingMetadataModel | None = None


def build_problem_details(
    status: ExitStatus,
    request: DocstringBuildRequest,
    detail: str,
    *,
    instance: str | None = None,
    errors: Sequence[ErrorReport] | None = None,
) -> ModelProblemDetails:
    """Create an RFC 9457 Problem Details payload for CLI failures.

    Parameters
    ----------
    status : ExitStatus
        Exit status code.
    request : DocstringBuildRequest
        Build request context.
    detail : str
        Error detail message.
    instance : str | None, optional
        Problem instance URI.
    errors : Sequence[ErrorReport] | None, optional
        Error reports to include in extensions.

    Returns
    -------
    ModelProblemDetails
        RFC 9457 Problem Details payload with extensions for command, subcommand, and error count.
    """
    command = request.command or "unknown"
    subcommand = request.invoked_subcommand or request.subcommand or command
    params = ProblemDetailsParams(
        type="https://kgfoundry.dev/problems/docbuilder/run-failed",
        title="Docstring builder run failed",
        status=http_status_for_exit(status),
        detail=detail,
        instance=instance or "",
        extensions=None,
    )
    problem_dict = _build_problem_details(params)
    problem_dict["extensions"] = {
        "command": command,
        "subcommand": subcommand,
        "errorCount": len(errors) if errors is not None else 0,
    }
    return cast("ModelProblemDetails", problem_dict)


__all__ = [
    "EXIT_CONFIG",
    "EXIT_ERROR",
    "EXIT_SUCCESS",
    "EXIT_VIOLATION",
    "STATUS_LABELS",
    "DocstringBuildRequest",
    "DocstringBuildResult",
    "ExitStatus",
    "LoggerLike",
    "StatusCounts",
    "build_problem_details",
    "http_status_for_exit",
    "status_from_exit",
    "status_from_label",
]
