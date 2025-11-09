"""Canonical docstring builder automation aligned with shared CLI metadata."""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    render_cli_envelope,
)
from tools._shared.error_codes import format_error_message
from tools._shared.logging import LoggerAdapter, get_logger, with_fields
from tools._shared.proc import ToolExecutionError, run_tool
from tools.docstring_builder import cli_context

LOGGER = get_logger(__name__)


REPO = Path(__file__).resolve().parents[1]
DOCFACTS = REPO / "docs" / "_build" / "docfacts.json"
CLI_ENVELOPE_DIR = REPO / "site" / "_build" / "cli"

CLI_COMMAND = cli_context.CLI_COMMAND
CLI_SETTINGS = cli_context.get_cli_settings()
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
UPDATE_SUBCOMMAND = "update"
UPDATE_OPERATION_ID = CLI_OPERATION_IDS[UPDATE_SUBCOMMAND]

_DEFAULT_PROBLEM_TYPE = "https://kgfoundry.dev/problems/docstrings/update-failed"


def _envelope_path(subcommand: str) -> Path:
    safe = subcommand or "root"
    return CLI_ENVELOPE_DIR / f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe}.json"


def _write_envelope(envelope: CliEnvelope, *, logger: LoggerAdapter) -> Path:
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    path = _envelope_path(UPDATE_SUBCOMMAND)
    rendered = render_cli_envelope(envelope)
    path.write_text(f"{rendered}\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
    return path


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _coerce_json_value(item) for key, item in value.items()}
    return str(value)


def _normalize_json_mapping(values: Mapping[str, object]) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {}
    for key, value in values.items():
        payload[str(key)] = _coerce_json_value(value)
    return payload


def _build_failure_problem(
    detail: str,
    *,
    status: int,
    extras: Mapping[str, object] | None = None,
) -> ProblemDetailsDict:
    extensions = _normalize_json_mapping(extras) if extras else None
    return build_problem_details(
        ProblemDetailsParams(
            type=_DEFAULT_PROBLEM_TYPE,
            title="Docstring builder update failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_SETTINGS.bin_name}:{UPDATE_SUBCOMMAND}",
            extensions=extensions,
        )
    )


def _prepare_failure_context(
    exc: ToolExecutionError,
    *,
    command: Sequence[str],
    args: Sequence[str],
) -> tuple[ProblemDetailsDict, str]:
    stderr = exc.stderr.strip()
    stdout = exc.stdout.strip()
    combined_details = "\n".join(part for part in (stderr, stdout) if part) or None

    error_code = "KGF-DOC-BLD-001"
    error_message = "Docstring builder failed"
    if combined_details:
        lowered = combined_details.lower()
        if "schema validation failed" in lowered or "schema_docfacts" in lowered:
            error_code = "KGF-DOC-BLD-006"
            error_message = "DocFacts schema validation failed during docstring build"
        elif "missing canonical schema" in lowered:
            error_code = "KGF-DOC-ENV-002"
            error_message = "DocFacts schema not found"

    formatted = format_error_message(error_code, error_message, details=combined_details)

    extras: dict[str, object] = {
        "command": " ".join(command),
        "args": list(args),
        "returncode": exc.returncode,
        "operation_id": UPDATE_OPERATION_ID,
        "error_code": error_code,
    }
    if combined_details:
        extras["details"] = combined_details
    if stderr:
        extras["stderr"] = stderr
    if stdout:
        extras["stdout"] = stdout

    problem = exc.problem
    if problem is None:
        problem = _build_failure_problem(formatted, status=500, extras=extras)
    else:
        # Copy to avoid mutating the original Problem Details payload.
        merged_problem: dict[str, Any] = {str(key): value for key, value in problem.items()}
        existing_extensions = {}
        extensions_raw = merged_problem.get("extensions")
        if isinstance(extensions_raw, Mapping):
            existing_extensions = _normalize_json_mapping(extensions_raw)
        existing_extensions.update(_normalize_json_mapping(extras))
        merged_problem["extensions"] = existing_extensions
        problem = cast("ProblemDetailsDict", merged_problem)

    return problem, formatted


def run_builder(extra_args: Sequence[str] | None = None) -> None:
    """Execute the docstring builder CLI with optional arguments.

    Parameters
    ----------
    extra_args : Sequence[str] | None
        Additional command-line arguments.

    Raises
    ------
    SystemExit
        If docstring builder execution fails.
    """
    args = list(extra_args or [])
    cmd = [
        sys.executable,
        "-m",
        "tools.docstring_builder.cli",
        UPDATE_SUBCOMMAND,
        *args,
    ]
    correlation_id = uuid4().hex
    logger = with_fields(
        LOGGER,
        correlation_id=correlation_id,
        command=CLI_COMMAND,
        subcommand=UPDATE_SUBCOMMAND,
        operation_id=UPDATE_OPERATION_ID,
        bin_name=CLI_SETTINGS.bin_name,
        args=args,
    )
    logger.info("Docstring builder update started", extra={"status": "start"})

    start = time.monotonic()
    try:
        result = run_tool(cmd, timeout=60.0, check=True)
    except ToolExecutionError as exc:
        problem, formatted = _prepare_failure_context(exc, command=cmd, args=args)

        failure_builder = CliEnvelopeBuilder.create(
            command=CLI_COMMAND,
            status="error",
            subcommand=UPDATE_SUBCOMMAND,
        )
        failure_builder = failure_builder.add_error(
            status="error", message=formatted, problem=problem
        )
        failure_builder = failure_builder.set_problem(problem)
        failure_builder = failure_builder.add_file(
            path=str(DOCFACTS),
            status="error",
            message="DocFacts artifact not updated",
        )
        if exc.stderr.strip():
            failure_builder = failure_builder.add_file(
                path="<stderr>",
                status="error",
                message=exc.stderr.strip(),
            )
        envelope = failure_builder.finish(duration_seconds=time.monotonic() - start)
        path = _write_envelope(envelope, logger=logger)
        logger.exception(
            formatted,
            extra={
                "status": "error",
                "returncode": exc.returncode,
                "cli_envelope": str(path),
                "duration_seconds": envelope.duration_seconds,
            },
        )
        raise SystemExit(exc.returncode if exc.returncode is not None else 1) from exc

    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status="success",
        subcommand=UPDATE_SUBCOMMAND,
    )
    if DOCFACTS.exists():
        builder = builder.add_file(
            path=str(DOCFACTS),
            status="success",
            message="DocFacts artifact synchronized",
        )
    else:
        builder = builder.add_file(
            path=str(DOCFACTS),
            status="skipped",
            message="DocFacts artifact not produced",
        )

    envelope = builder.finish(duration_seconds=result.duration_seconds)
    path = _write_envelope(envelope, logger=logger)
    logger.info(
        "Docstring builder update completed",
        extra={
            "status": "success",
            "cli_envelope": str(path),
            "duration_seconds": envelope.duration_seconds,
        },
    )


def main() -> None:
    """Entry point used by ``make docstrings`` and pre-commit hooks."""
    DOCFACTS.parent.mkdir(parents=True, exist_ok=True)
    run_builder()


if __name__ == "__main__":
    main()
