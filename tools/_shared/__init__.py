"""Shared utilities for tooling packages."""

from __future__ import annotations

from tools._shared.cli import (
    CLI_ENVELOPE_SCHEMA_ID,
    CLI_ENVELOPE_SCHEMA_VERSION,
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorEntry,
    CliErrorStatus,
    CliFileResult,
    CliFileStatus,
    CliStatus,
    new_cli_envelope,
    render_cli_envelope,
    validate_cli_envelope,
)
from tools._shared.logging import StructuredLoggerAdapter, get_logger, with_fields
from tools._shared.metrics import ToolRunObservation, observe_tool_run
from tools._shared.problem_details import (
    ProblemDetailsDict,
    build_problem_details,
    build_schema_problem_details,
    build_tool_problem_details,
    problem_from_exception,
    render_problem,
    tool_digest_mismatch_problem_details,
    tool_disallowed_problem_details,
    tool_failure_problem_details,
    tool_missing_problem_details,
    tool_timeout_problem_details,
)
from tools._shared.proc import (
    ProcessRunner,
    ToolExecutionError,
    ToolRunResult,
    get_process_runner,
    run_tool,
    set_process_runner,
)
from tools._shared.schema import get_schema_path, validate_tools_payload
from tools._shared.settings import (
    SettingsError,
    ToolRuntimeSettings,
    get_runtime_settings,
)
from tools._shared.validation import (
    ValidationError,
    require_directory,
    require_file,
    resolve_path,
)

__all__ = [
    "CLI_ENVELOPE_SCHEMA_ID",
    "CLI_ENVELOPE_SCHEMA_VERSION",
    "CliEnvelope",
    "CliEnvelopeBuilder",
    "CliErrorEntry",
    "CliErrorStatus",
    "CliFileResult",
    "CliFileStatus",
    "CliStatus",
    "ProblemDetailsDict",
    "ProcessRunner",
    "SettingsError",
    "StructuredLoggerAdapter",
    "ToolExecutionError",
    "ToolRunObservation",
    "ToolRunResult",
    "ToolRuntimeSettings",
    "ValidationError",
    "build_problem_details",
    "build_schema_problem_details",
    "build_tool_problem_details",
    "get_logger",
    "get_process_runner",
    "get_runtime_settings",
    "get_schema_path",
    "new_cli_envelope",
    "observe_tool_run",
    "problem_from_exception",
    "render_cli_envelope",
    "render_problem",
    "require_directory",
    "require_file",
    "resolve_path",
    "run_tool",
    "set_process_runner",
    "tool_digest_mismatch_problem_details",
    "tool_disallowed_problem_details",
    "tool_failure_problem_details",
    "tool_missing_problem_details",
    "tool_timeout_problem_details",
    "validate_cli_envelope",
    "validate_tools_payload",
    "with_fields",
]
