"""Typed models and schemas for the docstring builder pipeline.

This module centralises the strongly typed intermediate representations used by the
docstring builder as well as the structures emitted through the CLI when the
``--json`` flag is enabled.  The definitions here are designed to remove the
dynamic ``dict[str, Any]`` payloads that currently trigger Ruff and static type
checker errors throughout ``tools/docstring_builder``.  None of the existing modules import this
file yet; it establishes the target shapes that follow-up refactors will adopt.

Key goals addressed by these models:

* Typed DocFacts payloads aligned with ``docs/_build/schema_docfacts.json``.
* A versioned CLI result envelope accompanied by a JSON Schema (see
  ``schema/tools/docstring_builder_cli.json``).
* A small exception taxonomy that preserves error causality and surfaces RFC 9457
  Problem Details payloads for downstream tooling.
* Enumerations and literals that document permissible values, closing the gaps
  responsible for the observed ``Any`` propagation in static analyzers and Ruff ``BLE001``/``T201``
  findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Final,
    Literal,
    NotRequired,
    Protocol,
    Required,
    TypedDict,
    cast,
)

from kgfoundry_common.jsonschema_utils import (
    ValidationError,
    create_draft202012_validator,
)
from tools._shared.problem_details import (
    ProblemDetailsParams,
    SchemaProblemDetailsParams,
    build_schema_problem_details,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kgfoundry_common.jsonschema_utils import (
        Draft202012ValidatorProtocol,
        ValidationErrorProtocol,
    )

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

CLI_SCHEMA_VERSION: Final = "1.0.0"
CLI_SCHEMA_ID: Final = "https://kgfoundry.dev/schema/docstring-builder-cli.json"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCFACTS_SCHEMA_PATH = _REPO_ROOT / "docs" / "_build" / "schema_docfacts.json"
_DOCFACTS_SCHEMA_FALLBACK = _REPO_ROOT / "schema" / "docs" / "schema_docfacts.json"
_CLI_SCHEMA_PATH = _REPO_ROOT / "schema" / "tools" / "docstring_builder_cli.json"


class ProblemDetails(TypedDict, total=False):
    """RFC 9457 Problem Details envelope used for error reporting."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    extensions: dict[str, JsonValue]


class DocstringBuilderError(RuntimeError):
    """Base exception for docstring builder failures."""


class SchemaViolationError(DocstringBuilderError):
    """Raised when generated payloads do not satisfy the published schema.

    Attributes
    ----------
    problem : ProblemDetails | None
        RFC 9457 Problem Details payload.

    Parameters
    ----------
    message : str
        Error message.
    problem : ProblemDetails | None, optional
        RFC 9457 Problem Details payload.
    """

    __slots__ = ("problem",)

    problem: ProblemDetails | None

    def __init__(self, message: str, *, problem: ProblemDetails | None = None) -> None:
        super().__init__(message)
        self.problem = problem


class PluginExecutionError(DocstringBuilderError):
    """Raised when a plugin fails during execution and cannot recover."""


class ToolConfigurationError(DocstringBuilderError):
    """Raised when CLI configuration (flags, environment, config files) is invalid."""


class SymbolResolutionError(DocstringBuilderError):
    """Raised when harvested symbols cannot be imported for inspection."""


class SignatureIntrospectionError(DocstringBuilderError):
    """Raised when callable signatures or annotations cannot be inspected."""


class RunStatus(StrEnum):
    """Enumerated status labels used across CLI summaries and manifest files."""

    SUCCESS = "success"
    VIOLATION = "violation"
    CONFIG = "config"
    ERROR = "error"


class DocfactsProvenanceLike(Protocol):
    """Structural typing contract for DocFacts provenance objects."""

    builder_version: str
    config_hash: str
    commit_hash: str
    generated_at: str


class DocFactLike(Protocol):
    """Structural view of DocFacts entries consumed by adapters."""

    qname: str
    module: str
    kind: str
    filepath: str
    lineno: int
    end_lineno: int | None
    decorators: Sequence[str]
    is_async: bool
    is_generator: bool
    owned: bool
    parameters: Sequence[Mapping[str, object]]
    returns: Sequence[Mapping[str, object]]
    raises: Sequence[Mapping[str, object]]
    notes: Sequence[str]


class DocfactsDocumentLike(Protocol):
    """Contract implemented by DocFacts document dataclasses."""

    docfacts_version: str
    provenance: DocfactsProvenanceLike
    entries: Sequence[DocFactLike]


class IRParameterLike(Protocol):
    """Minimal parameter fields required from legacy IR objects."""

    name: str
    display_name: str | None
    kind: str
    annotation: str | None
    default: str | None
    optional: bool
    description: str


class IRReturnLike(Protocol):
    """Minimal return metadata required from legacy IR objects."""

    kind: Literal["returns", "yields"]
    annotation: str | None
    description: str


class IRRaiseLike(Protocol):
    """Minimal raise metadata required from legacy IR objects."""

    exception: str
    description: str


class IRDocstringLike(Protocol):
    """Structural view of legacy docstring IR objects."""

    symbol_id: str
    module: str
    kind: str
    source_path: str
    lineno: int
    ir_version: str
    summary: str
    extended: str | None
    parameters: Sequence[IRParameterLike]
    returns: Sequence[IRReturnLike]
    raises: Sequence[IRRaiseLike]
    notes: Sequence[str]


ParameterKind = Literal[
    "positional_only",
    "positional_or_keyword",
    "keyword_only",
    "var_positional",
    "var_keyword",
]

_PARAMETER_KINDS: Final = {
    "positional_only",
    "positional_or_keyword",
    "keyword_only",
    "var_positional",
    "var_keyword",
}

SymbolKind = Literal["function", "method", "class"]

_SYMBOL_KINDS: Final = {"function", "method", "class"}

_RETURN_KINDS: Final = {"returns", "yields"}


PROBLEM_DETAILS_EXAMPLE: ProblemDetails = {
    "type": "https://kgfoundry.dev/problems/docbuilder/schema-mismatch",
    "title": "DocFacts schema validation failed",
    "status": 422,
    "detail": "Field anchors.endLine is missing",
    "instance": "urn:docbuilder:run:2025-10-30T12:00:00Z",
    "extensions": {
        "schemaVersion": "2.0.0",
        "docstringBuilderVersion": "1.6.0",
        "symbol": "kg.module.function",
    },
}
"""Example Problem Details payload conforming to RFC 9457.

Examples
--------
>>> from tools.docstring_builder.models import PROBLEM_DETAILS_EXAMPLE
>>> import json
>>> payload = json.dumps(PROBLEM_DETAILS_EXAMPLE, indent=2)
>>> assert "type" in payload
>>> assert "status" in payload
>>> assert PROBLEM_DETAILS_EXAMPLE["status"] == 422
>>> assert PROBLEM_DETAILS_EXAMPLE["type"].startswith("https://kgfoundry.dev/problems/")
"""


@dataclass(slots=True, frozen=True)
class DocstringIRParameter:
    """Typed representation of a parameter within the docstring IR."""

    name: str
    display_name: str
    kind: ParameterKind
    annotation: str | None = None
    default: str | None = None
    optional: bool = False
    description: str = ""


@dataclass(slots=True, frozen=True)
class DocstringIRReturn:
    """Typed representation of a return or yield section."""

    kind: Literal["returns", "yields"]
    annotation: str | None = None
    description: str = ""


@dataclass(slots=True, frozen=True)
class DocstringIRRaise:
    """Typed representation of an exception raised by the symbol."""

    exception: str
    description: str = ""


@dataclass(slots=True, frozen=True)
class DocstringIR:
    """Aggregate typed intermediate representation for a symbol's docstring."""

    symbol_id: str
    module: str
    kind: SymbolKind
    source_path: str
    lineno: int
    end_lineno: int | None
    ir_version: str
    summary: str
    extended: str | None = None
    parameters: list[DocstringIRParameter] = field(default_factory=list)
    returns: list[DocstringIRReturn] = field(default_factory=list)
    raises: list[DocstringIRRaise] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class DocfactsParameter(TypedDict, total=False):
    """JSON representation of a parameter preserved in DocFacts."""

    name: str
    display_name: str
    annotation: str | None
    optional: bool | None
    default: str | None
    kind: ParameterKind | None


class DocfactsReturn(TypedDict, total=False):
    """JSON representation of return metadata inside DocFacts."""

    kind: Literal["returns", "yields"]
    annotation: str | None
    description: str | None


class DocfactsRaise(TypedDict, total=False):
    """JSON representation of exception metadata inside DocFacts."""

    exception: str
    description: str | None


class DocfactsEntry(TypedDict, total=False):
    """Typed DocFacts entry aligned with ``schema_docfacts.json``."""

    qname: str
    module: str
    kind: SymbolKind
    filepath: str
    lineno: int
    end_lineno: int | None
    decorators: list[str]
    is_async: bool
    is_generator: bool
    owned: bool
    parameters: list[DocfactsParameter]
    returns: list[DocfactsReturn]
    raises: list[DocfactsRaise]
    notes: list[str]


class DocfactsProvenancePayload(TypedDict):
    """Provenance metadata stored alongside DocFacts outputs."""

    builderVersion: str
    configHash: str
    commitHash: str
    generatedAt: str


class DocfactsDocumentPayload(TypedDict):
    """Canonical DocFacts document payload."""

    docfactsVersion: str
    provenance: DocfactsProvenancePayload
    entries: list[DocfactsEntry]


class FileReport(TypedDict, total=False):
    """File-level result emitted by the CLI ``--json`` output."""

    path: str
    status: RunStatus
    changed: bool
    skipped: bool
    cacheHit: bool
    message: str
    preview: str
    baseline: str
    problem: ProblemDetails


class ErrorReport(TypedDict, total=False):
    """Summary of a failure encountered during processing.

    This TypedDict uses PEP 655 Required/NotRequired to clearly partition fields.
    - Required: file, status, message
    - Optional: problem

    Attributes
    ----------
    file : Required[str]
        File path where the error occurred.
    status : Required[str]
        Status string indicating the error type.
    message : Required[str]
        Error message describing the failure.
    problem : NotRequired[ProblemDetails]
        Optional RFC 9457 Problem Details payload.

    Examples
    --------
    >>> error = ErrorReport(file="example.py", status="error", message="Build failed")
    >>> error_with_problem = error | {"problem": {...}}
    """

    file: Required[str]
    status: Required[str]
    message: Required[str]
    problem: NotRequired[ProblemDetails]


def make_error_report(
    file: str,
    status: str,
    message: str,
    *,
    problem: ProblemDetails | None = None,
) -> ErrorReport:
    """Construct an ErrorReport with required fields and optional problem details.

    Parameters
    ----------
    file : str
        File path where error occurred.
    status : str
        Error status (e.g., "error", "violation", "config").
    message : str
        Error message.
    problem : ProblemDetails | None, optional
        RFC 9457 Problem Details payload. Defaults to ``None``.

    Returns
    -------
    ErrorReport
        Fully-initialized error report.

    Examples
    --------
    >>> error = make_error_report(
    ...     file="module.py", status="error", message="Failed to build docstring"
    ... )
    >>> error["file"]
    'module.py'
    """
    result: ErrorReport = {"file": file, "status": status, "message": message}
    if problem is not None:
        result["problem"] = problem
    return result


class PolicyViolationReport(TypedDict):
    """Single policy engine violation entry."""

    rule: str
    symbol: str
    action: str
    message: str


class PolicyReport(TypedDict):
    """Aggregated policy engine results for a run."""

    coverage: float
    threshold: float
    violations: list[PolicyViolationReport]


class StatusCounts(TypedDict):
    """Mapping of :class:`RunStatus` to processed file counts."""

    success: int
    violation: int
    config: int
    error: int


class RunSummary(TypedDict, total=False):
    """Run summary statistics published in CLI output."""

    considered: int
    processed: int
    skipped: int
    changed: int
    status_counts: StatusCounts
    docfacts_checked: bool
    cache_hits: int
    cache_misses: int
    duration_seconds: float
    subcommand: str


class CacheSummary(TypedDict, total=False):
    """Cache metadata captured for observability and diagnostics."""

    path: str
    exists: bool
    hits: int
    misses: int
    mtime: str | None


class InputHash(TypedDict):
    """File hash metadata tracked for reproducibility."""

    hash: str
    mtime: str | None


class PluginReport(TypedDict):
    """Plugin execution overview included in CLI results."""

    enabled: list[str]
    available: list[str]
    disabled: list[str]
    skipped: list[str]


class DocfactsReport(TypedDict, total=False):
    """DocFacts summary embedded in CLI output."""

    path: str
    version: str
    diff: str | None
    validated: bool


class ObservabilityReport(TypedDict, total=False):
    """Observability payload mirrored in CLI results."""

    status: RunStatus
    errors: list[ErrorReport]
    driftPreviews: dict[str, str]


class CliResultOptionalFields(TypedDict, total=False):
    """Optional fields for CliResult construction."""

    subcommand: str
    durationSeconds: float
    files: list[FileReport]
    errors: list[ErrorReport]
    summary: RunSummary
    policy: PolicyReport
    baseline: str
    cache: CacheSummary
    inputs: dict[str, InputHash]
    plugins: PluginReport
    docfacts: DocfactsReport
    observability: ObservabilityReport
    problem: ProblemDetails


CliResultOptionalKey = Literal[
    "subcommand",
    "durationSeconds",
    "files",
    "errors",
    "summary",
    "policy",
    "baseline",
    "cache",
    "inputs",
    "plugins",
    "docfacts",
    "observability",
    "problem",
]

_CLI_OPTIONAL_KEYS: tuple[CliResultOptionalKey, ...] = (
    "subcommand",
    "durationSeconds",
    "files",
    "errors",
    "summary",
    "policy",
    "baseline",
    "cache",
    "inputs",
    "plugins",
    "docfacts",
    "observability",
    "problem",
)


class CliResult(TypedDict, total=False):
    """Fully-typed structure matching ``schema/tools/docstring_builder_cli.json``.

    This TypedDict uses PEP 655 Required/NotRequired to clearly partition fields.
    - Required: schemaVersion, schemaId, status, generatedAt, command
    - Optional: subcommand, durationSeconds, files, errors, summary, policy,
      baseline, cache, inputs, plugins, docfacts, observability, problem

    Attributes
    ----------
    schemaVersion : Required[str]
        Schema version identifier.
    schemaId : Required[str]
        Schema identifier URI.
    status : Required[str]
        Overall status of the operation.
    generatedAt : Required[str]
        ISO 8601 timestamp when the result was generated.
    command : Required[str]
        Main command that was executed.
    subcommand : NotRequired[str]
        Optional subcommand.
    durationSeconds : NotRequired[float]
        Duration of the operation in seconds.
    files : NotRequired[list[FileReport]]
        List of file processing results.
    errors : NotRequired[list[ErrorReport]]
        List of error reports.
    summary : NotRequired[RunSummary]
        Summary of the run.
    policy : NotRequired[PolicyReport]
        Policy validation report.
    baseline : NotRequired[str]
        Baseline version identifier.
    cache : NotRequired[CacheSummary]
        Cache summary.
    inputs : NotRequired[dict[str, InputHash]]
        Input file hashes.
    plugins : NotRequired[PluginReport]
        Plugin execution report.
    docfacts : NotRequired[DocfactsReport]
        DocFacts generation report.
    observability : NotRequired[ObservabilityReport]
        Observability metrics report.
    problem : NotRequired[ProblemDetails]
        RFC 9457 Problem Details payload if applicable.

    Examples
    --------
    >>> result = CliResult(
    ...     schemaVersion="1.0.0",
    ...     schemaId="https://kgfoundry.dev/schema/docstring-builder-cli.json",
    ...     status="success",
    ...     generatedAt="2024-11-03T00:00:00Z",
    ...     command="build",
    ... )
    """

    schemaVersion: Required[str]
    schemaId: Required[str]
    status: Required[str]
    generatedAt: Required[str]
    command: Required[str]
    subcommand: NotRequired[str]
    durationSeconds: NotRequired[float]
    files: NotRequired[list[FileReport]]
    errors: NotRequired[list[ErrorReport]]
    summary: NotRequired[RunSummary]
    policy: NotRequired[PolicyReport]
    baseline: NotRequired[str]
    cache: NotRequired[CacheSummary]
    inputs: NotRequired[dict[str, InputHash]]
    plugins: NotRequired[PluginReport]
    docfacts: NotRequired[DocfactsReport]
    observability: NotRequired[ObservabilityReport]
    problem: NotRequired[ProblemDetails]


def _build_required_fields(
    status: str,
    command: str,
    *,
    schema_version: str = CLI_SCHEMA_VERSION,
    schema_id: str = CLI_SCHEMA_ID,
) -> dict[str, str]:
    """Build required fields for CliResult.

    Parameters
    ----------
    status : str
        Result status ("success", "violation", "config", "error").
    command : str
        Primary CLI command executed.
    schema_version : str, optional
        Schema version. Defaults to ``CLI_SCHEMA_VERSION``.
    schema_id : str, optional
        Schema URI. Defaults to ``CLI_SCHEMA_ID``.

    Returns
    -------
    dict[str, str]
        Required fields dictionary.
    """
    return {
        "schemaVersion": schema_version,
        "schemaId": schema_id,
        "status": status,
        "generatedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "command": command,
    }


def _copy_optional_field(
    result: dict[str, object],
    optional: CliResultOptionalFields,
    key: CliResultOptionalKey,
) -> None:
    value = optional.get(key)
    if value is not None:
        result[key] = value


def _add_optional_fields(
    result: dict[str, object], optional: CliResultOptionalFields | None = None
) -> None:
    """Add optional fields to CliResult if provided.

    Parameters
    ----------
    result : dict[str, object]
        Result dictionary to modify in-place.
    optional : CliResultOptionalFields | None, optional
        Optional fields dictionary. Defaults to ``None``.
    """
    if optional is None:
        return

    for key in _CLI_OPTIONAL_KEYS:
        _copy_optional_field(result, optional, key)


def make_cli_result(
    status: str,
    command: str,
    *,
    schema_version: str = CLI_SCHEMA_VERSION,
    schema_id: str = CLI_SCHEMA_ID,
    optional: CliResultOptionalFields | None = None,
) -> CliResult:
    """Construct a CliResult with required fields and optional extended details.

    Parameters
    ----------
    status : str
        Result status ("success", "violation", "config", "error").
    command : str
        Primary CLI command executed.
    schema_version : str, optional
        Schema version. Defaults to ``CLI_SCHEMA_VERSION``.
    schema_id : str, optional
        Schema URI. Defaults to ``CLI_SCHEMA_ID``.
    optional : CliResultOptionalFields | None, optional
        Optional fields dictionary. Defaults to ``None``.

    Returns
    -------
    CliResult
        Fully-initialized CLI result.

    Examples
    --------
    >>> result = make_cli_result(status="success", command="build")
    >>> result["status"]
    'success'
    >>> optional = {"subcommand": "docstrings"}
    >>> result = make_cli_result(status="success", command="build", optional=optional)
    >>> result.get("subcommand")
    'docstrings'
    """
    required_fields = _build_required_fields(
        status,
        command,
        schema_version=schema_version,
        schema_id=schema_id,
    )
    result_fields: dict[str, object] = {**required_fields}
    _add_optional_fields(result_fields, optional)
    return cast("CliResult", result_fields)


def _load_docfacts_schema() -> dict[str, JsonValue]:
    try:
        schema_text = _DOCFACTS_SCHEMA_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        try:
            fallback_text = _DOCFACTS_SCHEMA_FALLBACK.read_text(encoding="utf-8")
        except FileNotFoundError as fallback_exc:  # pragma: no cover - defensive guard
            message = (
                f"DocFacts schema missing at {_DOCFACTS_SCHEMA_PATH} "
                f"and fallback {_DOCFACTS_SCHEMA_FALLBACK}"
            )
            raise RuntimeError(message) from fallback_exc
        _DOCFACTS_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DOCFACTS_SCHEMA_PATH.write_text(fallback_text, encoding="utf-8")
        schema_text = fallback_text
    return cast("dict[str, JsonValue]", json.loads(schema_text))


_DOCFACTS_VALIDATOR: Final[Draft202012ValidatorProtocol] = create_draft202012_validator(
    _load_docfacts_schema()
)
_CLI_VALIDATOR: Final[Draft202012ValidatorProtocol] = create_draft202012_validator(
    cast(
        "dict[str, JsonValue]", json.loads(_CLI_SCHEMA_PATH.read_text(encoding="utf-8"))
    )
)


def _load_docfacts_validator() -> Draft202012ValidatorProtocol:
    return _DOCFACTS_VALIDATOR


def _load_cli_validator() -> Draft202012ValidatorProtocol:
    return _CLI_VALIDATOR


def validate_docfacts_payload(payload: DocfactsDocumentPayload) -> None:
    """Validate ``payload`` against the published DocFacts schema.

    Parameters
    ----------
    payload : DocfactsDocumentPayload
        Payload dictionary to validate.

    Raises
    ------
    SchemaViolationError
        If the payload fails schema validation.
    """
    validator = _load_docfacts_validator()
    try:
        validator.validate(payload)
    except ValidationError as exc:
        schema_version = payload.get("docfactsVersion")
        problem = build_schema_problem_details(
            SchemaProblemDetailsParams(
                base=ProblemDetailsParams(
                    type="https://kgfoundry.dev/problems/docbuilder/docfacts-schema-mismatch",
                    title="DocFacts schema validation failed",
                    status=422,
                    detail="",
                    instance=(
                        f"urn:docbuilder:schema:docfacts:{datetime.now(tz=UTC).isoformat(timespec='seconds')}"
                    ),
                ),
                error=exc,
                extensions={"schemaVersion": schema_version or ""},
            )
        )
        problem_payload = cast("ProblemDetails", problem)
        detail_message = str(
            problem_payload.get("detail", "DocFacts schema validation failed")
        )
        raise SchemaViolationError(detail_message, problem=problem_payload) from exc


def validate_cli_output(payload: CliResult) -> None:
    """Validate CLI machine output against the JSON schema.

    Parameters
    ----------
    payload : CliResult
        CLI result dictionary to validate.

    Raises
    ------
    SchemaViolationError
        If the payload fails schema validation.
    """
    validator = _load_cli_validator()
    try:
        validator.validate(payload)
    except ValidationError as exc:
        schema_version = payload.get("schemaVersion")
        problem = build_schema_problem_details(
            SchemaProblemDetailsParams(
                base=ProblemDetailsParams(
                    type="https://kgfoundry.dev/problems/docbuilder/cli-schema-mismatch",
                    title="CLI schema validation failed",
                    status=422,
                    detail="",
                    instance=(
                        f"urn:docbuilder:schema:cli:{datetime.now(tz=UTC).isoformat(timespec='seconds')}"
                    ),
                ),
                error=exc,
                extensions={"schemaVersion": schema_version or ""},
            )
        )
        problem_payload = cast("ProblemDetails", problem)
        detail_message = str(
            problem_payload.get("detail", "CLI schema validation failed")
        )
        raise SchemaViolationError(detail_message, problem=problem_payload) from exc


def _normalise_parameter(parameter: Mapping[str, object]) -> DocfactsParameter:
    name = str(parameter.get("name", ""))
    display_name = parameter.get("display_name")
    entry: DocfactsParameter = {
        "name": name,
        "display_name": str(display_name) if display_name is not None else name,
    }
    annotation = parameter.get("annotation")
    entry["annotation"] = str(annotation) if annotation is not None else None
    optional_flag = parameter.get("optional")
    entry["optional"] = bool(optional_flag) if optional_flag is not None else None
    default_value = parameter.get("default")
    entry["default"] = str(default_value) if default_value is not None else None
    kind_value = parameter.get("kind")
    if isinstance(kind_value, str) and kind_value in _PARAMETER_KINDS:
        entry["kind"] = cast("ParameterKind", kind_value)
    else:
        entry["kind"] = "positional_or_keyword"
    return entry


def _normalise_return(value: Mapping[str, object]) -> DocfactsReturn:
    kind_raw = str(value.get("kind", "returns"))
    entry: DocfactsReturn = {
        "kind": (
            cast("Literal['returns', 'yields']", kind_raw)
            if kind_raw in _RETURN_KINDS
            else "returns"
        ),
    }
    annotation = value.get("annotation")
    entry["annotation"] = str(annotation) if annotation is not None else None
    description = value.get("description")
    entry["description"] = str(description) if description is not None else None
    return entry


def _normalise_raise(value: Mapping[str, object]) -> DocfactsRaise:
    entry: DocfactsRaise = {
        "exception": str(value.get("exception", "")),
    }
    description = value.get("description")
    entry["description"] = str(description) if description is not None else None
    return entry


def _build_docfacts_entry(fact: DocFactLike) -> DocfactsEntry:
    return {
        "qname": fact.qname,
        "module": fact.module,
        "kind": (
            cast("SymbolKind", fact.kind) if fact.kind in _SYMBOL_KINDS else "function"
        ),
        "filepath": fact.filepath,
        "lineno": fact.lineno,
        "end_lineno": fact.end_lineno,
        "decorators": list(fact.decorators),
        "is_async": fact.is_async,
        "is_generator": fact.is_generator,
        "owned": fact.owned,
        "parameters": [_normalise_parameter(param) for param in fact.parameters],
        "returns": [_normalise_return(value) for value in fact.returns],
        "raises": [_normalise_raise(value) for value in fact.raises],
        "notes": list(fact.notes),
    }


def build_docfacts_document_payload(
    document: DocfactsDocumentLike,
) -> DocfactsDocumentPayload:
    """Convert a legacy :class:`DocfactsDocument` to the typed payload shape.

    Parameters
    ----------
    document : DocfactsDocumentLike
        Document instance to convert.

    Returns
    -------
    DocfactsDocumentPayload
        Typed payload dictionary.
    """
    entries = [_build_docfacts_entry(fact) for fact in document.entries]
    provenance = document.provenance
    payload: DocfactsDocumentPayload = {
        "docfactsVersion": document.docfacts_version,
        "provenance": {
            "builderVersion": provenance.builder_version,
            "configHash": provenance.config_hash,
            "commitHash": provenance.commit_hash,
            "generatedAt": provenance.generated_at,
        },
        "entries": entries,
    }
    return payload


def build_docstring_ir_from_legacy(ir: IRDocstringLike) -> DocstringIR:
    """Convert a legacy IR object into the typed :class:`DocstringIR`.

    Parameters
    ----------
    ir : IRDocstringLike
        Legacy IR docstring instance.

    Returns
    -------
    DocstringIR
        Typed IR docstring instance.
    """
    parameters = [
        DocstringIRParameter(
            name=parameter.name,
            display_name=parameter.display_name or parameter.name,
            kind=_coerce_parameter_kind(parameter.kind),
            annotation=parameter.annotation,
            default=parameter.default,
            optional=parameter.optional,
            description=parameter.description,
        )
        for parameter in ir.parameters
    ]
    returns = [
        DocstringIRReturn(
            kind=ret.kind,
            annotation=ret.annotation,
            description=ret.description,
        )
        for ret in ir.returns
    ]
    raises = [
        DocstringIRRaise(exception=item.exception, description=item.description)
        for item in ir.raises
    ]
    return DocstringIR(
        symbol_id=ir.symbol_id,
        module=ir.module,
        kind=_coerce_symbol_kind(ir.kind),
        source_path=ir.source_path,
        lineno=ir.lineno,
        end_lineno=None,
        ir_version=ir.ir_version,
        summary=ir.summary,
        extended=ir.extended,
        parameters=parameters,
        returns=returns,
        raises=raises,
        notes=list(ir.notes),
    )


def build_cli_result_skeleton(status: RunStatus) -> CliResult:
    """Return a minimal CLI result payload initialised with required fields.

    Parameters
    ----------
    status : RunStatus
        Status code for the result.

    Returns
    -------
    CliResult
        Minimal CLI result dictionary with required fields populated.
    """
    payload: CliResult = {
        "schemaVersion": CLI_SCHEMA_VERSION,
        "schemaId": CLI_SCHEMA_ID,
        "status": status,
        "generatedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "command": "",
    }
    return payload


def _json_pointer_from(error: ValidationErrorProtocol) -> str | None:
    raw_path = cast("Sequence[object]", getattr(error, "absolute_path", ()))
    tokens: list[str] = []
    for part in raw_path:
        if part is None:
            continue
        tokens.append(str(part))
    if tokens:
        return "/" + "/".join(tokens)
    return None


def _coerce_parameter_kind(kind: str | None) -> ParameterKind:
    if kind in _PARAMETER_KINDS:
        return cast("ParameterKind", kind)
    return "positional_or_keyword"


def _coerce_symbol_kind(kind: str | None) -> SymbolKind:
    if kind in _SYMBOL_KINDS:
        return cast("SymbolKind", kind)
    return "function"


__all__: tuple[str, ...] = (
    "CLI_SCHEMA_ID",
    "CLI_SCHEMA_VERSION",
    "PROBLEM_DETAILS_EXAMPLE",
    "CacheSummary",
    "CliResult",
    "DocFactLike",
    "DocfactsDocumentLike",
    "DocfactsDocumentPayload",
    "DocfactsEntry",
    "DocfactsParameter",
    "DocfactsProvenanceLike",
    "DocfactsProvenancePayload",
    "DocfactsRaise",
    "DocfactsReport",
    "DocfactsReturn",
    "DocstringBuilderError",
    "DocstringIR",
    "DocstringIRParameter",
    "DocstringIRRaise",
    "DocstringIRReturn",
    "ErrorReport",
    "FileReport",
    "IRDocstringLike",
    "IRParameterLike",
    "IRRaiseLike",
    "IRReturnLike",
    "InputHash",
    "ObservabilityReport",
    "PluginExecutionError",
    "PluginReport",
    "PolicyReport",
    "PolicyViolationReport",
    "ProblemDetails",
    "RunStatus",
    "RunSummary",
    "SchemaViolationError",
    "SignatureIntrospectionError",
    "StatusCounts",
    "SymbolResolutionError",
    "ToolConfigurationError",
    "build_cli_result_skeleton",
    "build_docfacts_document_payload",
    "build_docstring_ir_from_legacy",
    "make_cli_result",
    "make_error_report",
    "validate_cli_output",
    "validate_docfacts_payload",
)
