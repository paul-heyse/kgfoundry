"""Command-line interface for validating documentation artifacts against schemas.

This module provides a CLI tool to validate all documentation artifacts (symbol
index, delta, reverse lookups) against their canonical JSON Schema definitions.
It ensures that all artifacts conform to the spec before they are written to disk.

The validator orchestrates calls to specialized functions for each artifact type
(see `validate_symbol_index`, `validate_symbol_delta`) and integrates with the
observability pipeline via:

- **Structured Logging**: each artifact validation produces logs with operation,
  artifact, and status fields via `shared.make_logger()` for correlation and tracing
- **Metrics**: duration and status captured via `observe_tool_run()` context manager
- **Error Handling**: all validation failures raise `ArtifactValidationError` with
  RFC 9457 Problem Details attached (`.problem` attr)

Correlation IDs
---------------
When invoked as part of a larger build orchestration, context propagates via
`contextvars` (see `tools._shared.contextvars` for details). Logs automatically
inherit correlation metadata from the calling context.

Examples
--------
Typical CLI usage::

    $ python -m docs._scripts.validate_artifacts --artifacts symbols.json
    ✓ symbols.json validated successfully

Programmatic usage::

    >>> from docs._scripts.validate_artifacts import validate_symbol_index
    >>> from pathlib import Path
    >>> artifacts = validate_symbol_index(Path("docs/_build/symbols.json"))
    >>> print(f"Validated {len(artifacts.rows)} symbols")
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    render_cli_envelope,
    with_fields,
)
from tools._shared.error_codes import format_error_message
from tools._shared.logging import LoggerAdapter
from tools._shared.proc import ToolExecutionError, run_tool

from docs._scripts import cli_context, shared
from docs._scripts.validation import validate_against_schema
from docs.types.artifacts import (
    symbol_delta_from_json,
    symbol_delta_to_payload,
    symbol_index_from_json,
    symbol_index_to_payload,
)
from kgfoundry_common.errors import (
    ArtifactDeserializationError as CoreArtifactDeserializationError,
)
from kgfoundry_common.errors import (
    ArtifactValidationError as CoreArtifactValidationError,
)

if TYPE_CHECKING:
    from docs.types.artifacts import (
        JsonPayload,
        SymbolDeltaPayload,
        SymbolIndexArtifacts,
    )

type ReverseLookup = dict[str, tuple[str, ...]]
type ReverseLookupPayload = dict[str, list[str]]

ENV = shared.detect_environment()
shared.ensure_sys_paths(ENV)
SETTINGS = shared.load_settings()
SCHEMA_ROOT = ENV.root / "schema" / "docs"

LOGGER = get_logger(__name__)

CLI_COMMAND = cli_context.CLI_COMMAND
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_SETTINGS = cli_context.get_cli_settings()
VALIDATE_SUBCOMMAND = "validate"
VALIDATE_OPERATION_ID = CLI_OPERATION_IDS[VALIDATE_SUBCOMMAND]
CLI_ENVELOPE_DIR = cli_context.REPO_ROOT / "site" / "_build" / "cli"
DEFAULT_DOCS_BUILD_DIR = cli_context.REPO_ROOT / "docs" / "_build"
_DEFAULT_PROBLEM_TYPE = "https://kgfoundry.dev/problems/docs/validate-artifacts"


class ArtifactValidationError(RuntimeError):
    """Exception raised when an artifact fails validation.

    This exception wraps validation failures with RFC 9457 Problem Details,
    providing structured error information suitable for CLI output and logging.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure.
    artifact_name : str
        Logical identifier for the artifact that failed validation.
    problem : ProblemDetailsDict | None, optional
        RFC 9457 Problem Details dict with validation error details.
        Defaults to empty dict if not provided.

    Notes
    -----
    The ``artifact_name`` and ``problem`` attributes are set as instance variables
    during initialization and can be accessed directly on the exception instance.
    """

    def __init__(
        self,
        message: str,
        artifact_name: str,
        problem: ProblemDetailsDict | None = None,
    ) -> None:
        super().__init__(message)
        self.artifact_name = artifact_name
        self.problem = problem or {}


def _resolve_schema(name: str) -> Path:
    """Return the absolute path to a documentation schema file.

    Parameters
    ----------
    name : str
        Schema filename.

    Returns
    -------
    Path
        Absolute path to the schema file.
    """
    return SCHEMA_ROOT / name


def _schema_path(filename: str) -> Path:
    """Return the absolute path to a docs schema file.

    Parameters
    ----------
    filename : str
        Schema filename.

    Returns
    -------
    Path
        Absolute path to the schema file.
    """
    return ENV.root / "schema" / "docs" / filename


def validate_symbol_index(path: Path) -> SymbolIndexArtifacts:
    """Validate a symbol index JSON file against its schema.

    Parameters
    ----------
    path : Path
        Path to the symbols.json file.

    Returns
    -------
    SymbolIndexArtifacts
        The validated artifact model.

    Raises
    ------
    ArtifactValidationError
        If the file doesn't exist, is invalid JSON, or fails schema validation.
    """
    if not path.exists():
        message = f"Symbol index not found: {path}"
        raise ArtifactValidationError(message, artifact_name="symbols.json")

    try:
        raw_data: JsonPayload = cast(
            "JsonPayload", json.loads(path.read_text(encoding="utf-8"))
        )
        artifacts = symbol_index_from_json(raw_data)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        message = f"Failed to parse symbol index: {e}"
        raise ArtifactValidationError(message, artifact_name="symbols.json") from e
    except (
        CoreArtifactValidationError,
        CoreArtifactDeserializationError,
    ) as exc:
        problem = cast("ProblemDetailsDict", exc.to_problem_details())
        raise ArtifactValidationError(
            str(exc),
            artifact_name="symbols.json",
            problem=problem,
        ) from exc

    schema = _resolve_schema("symbol-index.schema.json")
    schema = _schema_path("symbol-index.schema.json")
    try:
        validate_against_schema(
            symbol_index_to_payload(artifacts), schema, artifact="symbols.json"
        )
    except ToolExecutionError as e:
        raise ArtifactValidationError(
            str(e),
            artifact_name="symbols.json",
            problem=e.problem,
        ) from e

    return artifacts


def validate_symbol_delta(path: Path) -> SymbolDeltaPayload:
    """Validate a symbol delta JSON file against its schema.

    Parameters
    ----------
    path : Path
        Path to the symbols.delta.json file.

    Returns
    -------
    SymbolDeltaPayload
        The validated artifact model.

    Raises
    ------
    ArtifactValidationError
        If the file doesn't exist, is invalid JSON, or fails schema validation.
    """
    if not path.exists():
        message = f"Symbol delta not found: {path}"
        raise ArtifactValidationError(message, artifact_name="symbols.delta.json")

    try:
        raw_data: JsonPayload = cast(
            "JsonPayload", json.loads(path.read_text(encoding="utf-8"))
        )
        payload = symbol_delta_from_json(raw_data)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        message = f"Failed to parse symbol delta: {e}"
        raise ArtifactValidationError(
            message, artifact_name="symbols.delta.json"
        ) from e
    except (
        CoreArtifactValidationError,
        CoreArtifactDeserializationError,
    ) as exc:
        problem = cast("ProblemDetailsDict", exc.to_problem_details())
        raise ArtifactValidationError(
            str(exc),
            artifact_name="symbols.delta.json",
            problem=problem,
        ) from exc

    schema = _resolve_schema("symbol-delta.schema.json")
    schema = _schema_path("symbol-delta.schema.json")
    try:
        validate_against_schema(
            symbol_delta_to_payload(payload), schema, artifact="symbols.delta.json"
        )
    except ToolExecutionError as e:
        raise ArtifactValidationError(
            str(e),
            artifact_name="symbols.delta.json",
            problem=e.problem,
        ) from e

    return payload


def _load_reverse_lookup(
    path: Path,
    *,
    artifact_name: str,
    schema_filename: str,
) -> ReverseLookup:
    """Load and validate a reverse lookup artifact.

    Parameters
    ----------
    path : Path
        Path to the reverse lookup JSON file.
    artifact_name : str
        Name of the artifact for error messages.
    schema_filename : str
        Schema filename for validation.

    Returns
    -------
    ReverseLookup
        Validated reverse lookup dictionary.

    Raises
    ------
    ArtifactValidationError
        If the file doesn't exist, is invalid JSON, or fails validation.
    """
    if not path.exists():
        message = f"Reverse lookup not found: {path}"
        raise ArtifactValidationError(message, artifact_name=artifact_name)

    try:
        raw_data: object = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        message = f"Failed to parse {artifact_name}: {e}"
        raise ArtifactValidationError(message, artifact_name=artifact_name) from e

    if not isinstance(raw_data, dict):
        message = f"{artifact_name} must be a JSON object mapping strings to arrays"
        raise ArtifactValidationError(message, artifact_name=artifact_name)

    raw_mapping = cast("dict[str, object]", raw_data)
    payload: ReverseLookupPayload = {}
    typed_lookup: ReverseLookup = {}
    for key, value in raw_mapping.items():
        if not isinstance(key, str) or not key:
            message = f"Invalid key in {artifact_name}: {key!r}"
            raise ArtifactValidationError(message, artifact_name=artifact_name)
        if not isinstance(value, list):
            message = f"{artifact_name} values must be arrays of strings"
            raise ArtifactValidationError(message, artifact_name=artifact_name)

        entries = cast("list[object]", value)
        values: list[str] = []
        for index, item in enumerate(entries):
            if not isinstance(item, str) or not item:
                message = f"{artifact_name} entries must be non-empty strings (key={key!r}, index={index})"
                raise ArtifactValidationError(message, artifact_name=artifact_name)
            values.append(item)

        payload[key] = values
        typed_lookup[key] = tuple(values)

    schema = _schema_path(schema_filename)
    try:
        validate_against_schema(payload, schema, artifact=artifact_name)
    except ToolExecutionError as e:
        raise ArtifactValidationError(
            str(e),
            artifact_name=artifact_name,
            problem=e.problem,
        ) from e

    return typed_lookup


def validate_by_file_lookup(path: Path) -> ReverseLookup:
    """Validate a by-file reverse lookup JSON file against its schema.

    Parameters
    ----------
    path : Path
        Path to the by_file.json file.

    Returns
    -------
    ReverseLookup
        Validated reverse lookup dictionary.
    """
    return _load_reverse_lookup(
        path,
        artifact_name="by_file.json",
        schema_filename="symbol-reverse-lookup.schema.json",
    )


def validate_by_module_lookup(path: Path) -> ReverseLookup:
    """Validate a by-module reverse lookup JSON file against its schema.

    Parameters
    ----------
    path : Path
        Path to the by_module.json file.

    Returns
    -------
    ReverseLookup
        Validated reverse lookup dictionary.
    """
    return _load_reverse_lookup(
        path,
        artifact_name="by_module.json",
        schema_filename="symbol-reverse-lookup.schema.json",
    )


def _envelope_path(subcommand: str) -> Path:
    safe = subcommand or "root"
    return CLI_ENVELOPE_DIR / f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe}.json"


def _write_envelope(envelope: CliEnvelope, *, logger: LoggerAdapter) -> Path:
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    path = _envelope_path(VALIDATE_SUBCOMMAND)
    rendered = render_cli_envelope(envelope)
    path.write_text(f"{rendered}\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
    return path


def _normalize_json_mapping(values: Mapping[str, object]) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {}
    for key, value in values.items():
        key_str = str(key)
        payload[key_str] = _coerce_json_value(value)
    return payload


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _coerce_json_value(v) for k, v in value.items()}
    return str(value)


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
            title="Documentation artifact validation failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_SETTINGS.bin_name}:{VALIDATE_SUBCOMMAND}",
            extensions=extensions,
        )
    )


def _parse_problem_from_stream(stderr: str) -> ProblemDetailsDict | None:
    for line in reversed(stderr.splitlines()):
        text = line.strip()
        if not text:
            continue
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and {
            "type",
            "title",
            "status",
            "detail",
        }.issubset(candidate.keys()):
            return cast("ProblemDetailsDict", candidate)
    return None


def _prepare_failure_context(
    exc: ToolExecutionError,
    *,
    command: Sequence[str],
    args: Sequence[str],
) -> tuple[ProblemDetailsDict, str]:
    stderr = exc.stderr.strip()
    stdout = exc.stdout.strip()
    combined_details = "\n".join(part for part in (stderr, stdout) if part) or None

    problem = exc.problem or _parse_problem_from_stream(stderr)

    error_code = "KGF-DOC-VAL-001"
    error_message = "Documentation artifact validation failed"

    formatted = format_error_message(
        error_code, error_message, details=combined_details
    )

    extras: dict[str, object] = {
        "command": " ".join(command),
        "args": list(args),
        "returncode": exc.returncode,
        "operation_id": VALIDATE_OPERATION_ID,
    }
    if combined_details:
        extras["details"] = combined_details
    if stderr:
        extras["stderr"] = stderr
    if stdout:
        extras["stdout"] = stdout

    if problem is None:
        problem = _build_failure_problem(formatted, status=500, extras=extras)
    else:
        merged: ProblemDetailsDict = {
            str(key): _coerce_json_value(value) for key, value in problem.items()
        }
        extensions_raw = merged.get("extensions")
        existing_extensions: dict[str, JsonValue] = {}
        if isinstance(extensions_raw, Mapping):
            existing_extensions = _normalize_json_mapping(extensions_raw)
        existing_extensions.update(_normalize_json_mapping(extras))
        merged["extensions"] = existing_extensions
        problem = merged

    return problem, formatted


def _resolve_docs_build_dir(args: Sequence[str]) -> Path:
    iterator = iter(range(len(args)))
    for index in iterator:
        arg = args[index]
        if arg == "--docs-build-dir" and index + 1 < len(args):
            return Path(args[index + 1]).resolve()
        if arg.startswith("--docs-build-dir="):
            _, value = arg.split("=", 1)
            return Path(value).resolve()
    return DEFAULT_DOCS_BUILD_DIR


def run_validator(args: Sequence[str] | None = None) -> int:
    forwarded = list(args or [])
    cmd = [sys.executable, "-m", "docs.toolchain.validate_artifacts", *forwarded]
    docs_build_dir = _resolve_docs_build_dir(forwarded)
    correlation_id = uuid4().hex
    logger = with_fields(
        LOGGER,
        correlation_id=correlation_id,
        command=CLI_COMMAND,
        subcommand=VALIDATE_SUBCOMMAND,
        operation_id=VALIDATE_OPERATION_ID,
        docs_build_dir=str(docs_build_dir),
        args=forwarded,
    )

    logger.info("Validation started", extra={"status": "start"})
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status="success",
        subcommand=VALIDATE_SUBCOMMAND,
    )

    start = time.monotonic()
    try:
        result = run_tool(cmd, timeout=120.0, check=True)
    except ToolExecutionError as exc:
        duration = time.monotonic() - start
        problem, formatted = _prepare_failure_context(exc, command=cmd, args=forwarded)
        failure_builder = CliEnvelopeBuilder.create(
            command=CLI_COMMAND,
            status="error",
            subcommand=VALIDATE_SUBCOMMAND,
        )
        failure_builder = failure_builder.add_error(
            status="error", message=formatted, problem=problem
        )
        failure_builder = failure_builder.set_problem(problem)
        failure_builder = failure_builder.add_file(
            path=str(docs_build_dir),
            status="error",
            message="Artifact validation failed",
            problem=problem,
        )
        envelope = failure_builder.finish(duration_seconds=duration)
        path = _write_envelope(envelope, logger=logger)
        logger.exception(
            formatted,
            extra={
                "status": "error",
                "cli_envelope": str(path),
                "duration_seconds": duration,
                "returncode": exc.returncode,
            },
        )
        raise SystemExit(exc.returncode if exc.returncode is not None else 1) from exc

    duration = result.duration_seconds
    builder = builder.add_file(
        path=str(docs_build_dir),
        status="success",
        message="Documentation artifacts validated",
    )
    envelope = builder.finish(duration_seconds=duration)
    path = _write_envelope(envelope, logger=logger)
    logger.info(
        "Validation completed",
        extra={
            "status": "success",
            "cli_envelope": str(path),
            "duration_seconds": envelope.duration_seconds,
        },
    )
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    return run_validator(args)


if __name__ == "__main__":
    raise SystemExit(main())
