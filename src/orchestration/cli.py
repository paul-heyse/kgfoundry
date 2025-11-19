"""Orchestration CLI integrated with shared tooling metadata and envelopes."""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import uuid4

import click
import typer
from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorStatus,
    CliStatus,
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    render_cli_envelope,
)

from kgfoundry.embeddings_sparse.bm25 import get_bm25
from kgfoundry_common.errors import ConfigurationError, IndexBuildError
from kgfoundry_common.jsonschema_utils import create_draft202012_validator
from kgfoundry_common.schema_helpers import load_schema
from kgfoundry_common.vector_types import (
    VectorBatch,
    VectorValidationError,
    coerce_vector_batch,
)
from orchestration import cli_context, safe_pickle
from orchestration.config import IndexCliConfig

if TYPE_CHECKING:
    from kgfoundry_common.jsonschema_utils import (
        Draft202012ValidatorProtocol,
        ValidationErrorProtocol,
    )


REPO_ROOT = cli_context.REPO_ROOT
"""Repository root used for locating CLI envelopes and artifacts."""


class _UvicornRun(Protocol):
    """Protocol for uvicorn run callable used for API server execution.

    This protocol defines the interface for uvicorn's run function, enabling
    type-safe invocation of the ASGI server. The protocol supports configuration
    of host, port, and reload behavior for development and production deployments.
    Used for dependency injection and testing of API server startup.

    Methods
    -------
    __call__(app, *, host, port, reload=False) -> None
        Execute the ASGI application using uvicorn. The app parameter specifies
        the application module path, while host and port control the server
        binding. Reload enables automatic reloading during development.
    """

    def __call__(
        self, app: str, *, host: str, port: int, reload: bool = False
    ) -> None:  # pragma: no cover - runtime contract
        """Protocol describing the uvicorn ``run`` callable."""


class _BM25Builder(Protocol):
    """Protocol for BM25 index builders supporting multiple backends.

    This protocol defines the interface for BM25 index construction, enabling
    type-safe interaction with both Lucene-based and pure Python BM25 implementations.
    The protocol supports building indexes from document collections, where each
    document is represented as a tuple of (document_id, metadata_dict). Used for
    dependency injection and backend abstraction in BM25 index construction.

    Methods
    -------
    build(docs) -> None
        Build a BM25 index from an iterable of documents. Each document is a tuple
        of (document_id, metadata_dict) where metadata_dict contains fields like
        "title", "section", and "body" for indexing. The index is persisted to
        the directory specified during builder initialization.
    """

    def build(
        self, docs: Iterable[tuple[str, dict[str, str]]]
    ) -> None:  # pragma: no cover - provided by get_bm25
        """Protocol describing lucene/pure BM25 builders."""


class ArtifactFS(Protocol):
    """Protocol describing filesystem interactions for CLI artifacts.

    This protocol defines the interface for filesystem operations used by the
    orchestration CLI for managing artifacts (indexes, vectors, envelopes).
    The protocol enables abstraction over filesystem implementations, supporting
    both local filesystem and potential future remote storage backends.

    Methods
    -------
    ensure_dir(directory) -> None
        Ensure that a directory exists, creating it and all parent directories
        if necessary. Equivalent to mkdir -p in shell, ensuring the directory
        structure is ready for file operations.
    write_text(path, content, *, encoding="utf-8") -> None
        Write text content to a file at the specified path. The file's parent
        directory is created if necessary. Content is written using the specified
        encoding (default UTF-8), enabling proper handling of Unicode text.
    """

    def ensure_dir(self, directory: Path) -> None:
        """Ensure directory exists, creating parent directories if needed."""
        ...

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        """Write text content to file, creating parent directories if needed."""
        ...


@dataclass(frozen=True)
class BM25BuildConfig:
    """Configuration for BM25 index builds.

    Attributes
    ----------
    chunks_path : str
        Path to the chunks JSONL file containing documents to index.
    backend : str
        Backend identifier for BM25 implementation (e.g., "lucene", "pure").
    index_dir : str
        Output directory path where the BM25 index will be built.
    """

    chunks_path: str
    backend: str
    index_dir: str


@dataclass(slots=True, frozen=True)
class _CommandContext:
    """Structured context shared across a single command invocation.

    Attributes
    ----------
    subcommand : str
        Name of the CLI subcommand being executed (e.g., "e2e", "build").
    operation_id : str
        Unique identifier for this command execution. Used for tracking
        and correlation in logs and envelopes.
    correlation_id : str
        Correlation identifier for grouping related operations across
        multiple commands or services.
    start : float
        Timestamp when the command started (from time.time()).
    envelope_dir : Path
        Directory path where CLI envelopes will be written for this command.
    """

    subcommand: str
    operation_id: str
    correlation_id: str
    start: float
    envelope_dir: Path

    def extensions(self, extras: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
        """Build Problem Details extensions dictionary from context.

        Parameters
        ----------
        extras : Mapping[str, object] | None, optional
            Additional key-value pairs to include in the extensions dictionary.

        Returns
        -------
        dict[str, JsonValue]
            Extensions dictionary containing operation_id, correlation_id, and any extras.
        """
        payload: dict[str, JsonValue] = {
            "operation_id": self.operation_id,
            "correlation_id": self.correlation_id,
        }
        if extras:
            for key, value in extras.items():
                payload[str(key)] = _coerce_extension_value(value)
        return payload


@dataclass(slots=True, frozen=True)
class OrchestrationCliContext:
    """Dependency injection context for orchestration CLI commands.

    Attributes
    ----------
    uuid_factory : Callable[[], str]
        Factory function that generates unique identifiers. Returns a string
        UUID suitable for operation and correlation IDs.
    bm25_builder : Callable[[BM25BuildConfig, logging.Logger], tuple[str, int]]
        Factory function that builds BM25 indexes. Takes configuration and
        logger, returns tuple of (index_path, doc_count).
    faiss_runner : Callable[[IndexCliConfig], dict[str, object]]
        Factory function that runs FAISS index builds. Takes index configuration,
        returns dictionary with build metadata.
    artifact_fs : ArtifactFS
        Filesystem abstraction for reading and writing CLI artifacts.
        Used for envelope persistence and artifact management.
    """

    uuid_factory: Callable[[], str]
    bm25_builder: Callable[[BM25BuildConfig, logging.Logger], tuple[str, int]]
    faiss_runner: Callable[[IndexCliConfig], dict[str, object]]
    artifact_fs: ArtifactFS

    @classmethod
    def production(cls) -> OrchestrationCliContext:
        """Return the production orchestration CLI context.

        Returns
        -------
        OrchestrationCliContext
            Context configured with production factories.
        """
        return cls(
            uuid_factory=lambda: uuid4().hex,
            bm25_builder=_default_bm25_builder,
            faiss_runner=_default_faiss_runner,
            artifact_fs=_LocalArtifactFS(),
        )


class _LocalArtifactFS:
    """Filesystem implementation backed by the local OS.

    This class provides a concrete implementation of the ArtifactFS protocol
    using Python's pathlib and standard library file operations. All operations
    are performed on the local filesystem, making this suitable for development
    and single-machine deployments. The implementation ensures directories exist
    before writing files and handles encoding properly.
    """

    def ensure_dir(self, directory: Path) -> None:
        """Ensure directory exists, creating parent directories if needed.

        This method creates the specified directory and all necessary parent
        directories using pathlib's mkdir with parents=True. The exist_ok flag
        ensures the operation succeeds even if the directory already exists,
        making this method idempotent.

        Parameters
        ----------
        directory : Path
            Directory path to ensure exists. The path may be absolute or relative,
            and all parent directories are created as needed.
        """
        _ = self
        directory.mkdir(parents=True, exist_ok=True)

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        """Write text content to file, creating parent directories if needed.

        This method writes text content to a file, ensuring the file's parent
        directory exists before writing. The method uses pathlib's write_text
        with the specified encoding, enabling proper handling of Unicode text
        and ensuring files are written atomically.

        Parameters
        ----------
        path : Path
            File path where content should be written. The file's parent directory
            is created if it doesn't exist.
        content : str
            Text content to write to the file. The content is encoded using the
            specified encoding before writing.
        encoding : str, optional
            Text encoding to use when writing the file. Defaults to "utf-8" for
            Unicode compatibility.
        """
        _ = self
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)


def _default_bm25_builder(
    config: BM25BuildConfig,
    logger: logging.Logger,
) -> tuple[str, int]:
    """Return default BM25 builder factory function for production use.

    This function serves as the default factory for BM25 index construction,
    delegating to _build_bm25_index with the provided configuration and logger.
    Used as the production implementation in OrchestrationCliContext, enabling
    dependency injection and testing with mock builders.

    Parameters
    ----------
    config : BM25BuildConfig
        Configuration specifying chunks path, backend type, and index directory.
        The configuration determines which BM25 backend to use and where to
        store the constructed index.
    logger : logging.Logger
        Logger instance for recording build progress and errors. Used to emit
        structured log events during index construction.

    Returns
    -------
    tuple[str, int]
        Tuple containing:
        - Backend name actually used for construction (may differ from requested
          if fallback occurs, e.g., "lucene" -> "pure").
        - Number of documents successfully indexed.

    Notes
    -----
    This function provides a standard interface for BM25 index construction,
    handling backend selection, document loading, and index persistence. The
    function may fall back to alternative backends if the requested backend
    fails, ensuring robust index construction even when optional dependencies
    are unavailable.
    """
    return _build_bm25_index(config, logger=logger)


def _default_faiss_runner(config: IndexCliConfig) -> dict[str, object]:
    """Return default FAISS runner factory function for production use.

    This function serves as the default factory for FAISS index construction,
    delegating to run_index_faiss with the provided configuration. Used as the
    production implementation in OrchestrationCliContext, enabling dependency
    injection and testing with mock runners.

    Parameters
    ----------
    config : IndexCliConfig
        Configuration specifying dense vectors path, output index path, FAISS
        factory string, and metric type. The configuration determines how the
        FAISS index is constructed and where it is stored.

    Returns
    -------
    dict[str, object]
        Build metadata dictionary containing vector_count and dimension fields.
        The metadata summarizes the constructed index for verification and
        downstream processing.

    Notes
    -----
    This function provides a standard interface for FAISS index construction,
    handling vector loading, validation, index building, and persistence. The
    function integrates with the CLI envelope system to produce structured
    build artifacts and error reporting.
    """
    return run_index_faiss(config=config)


CLI_COMMAND = cli_context.CLI_COMMAND
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_INTERFACE_ID = cli_context.CLI_INTERFACE_ID
CLI_CONFIG = cli_context.get_cli_config()
CLI_SETTINGS = cli_context.get_cli_settings()
CLI_TITLE = cli_context.CLI_TITLE


def _default_envelope_dir() -> Path:
    """Determine the default directory for CLI envelope output.

    This function computes the default location where CLI envelopes (structured
    JSON artifacts containing command execution metadata) are written. The
    directory is located under the repository root in the site build directory,
    ensuring envelopes are stored alongside other build artifacts.

    Returns
    -------
    Path
        Default envelope directory path. The path is relative to the repository
        root and points to site/_build/cli, where all CLI execution envelopes
        are stored for analysis and tooling integration.

    Notes
    -----
    Envelope directories enable structured output from CLI commands, providing
    machine-readable metadata about command execution, results, and errors.
    The default location ensures envelopes are accessible to build tooling and
    CI/CD pipelines while remaining separate from source code.
    """
    return cli_context.REPO_ROOT / "site" / "_build" / "cli"


SUBCOMMAND_INDEX_BM25 = "index-bm25"
SUBCOMMAND_INDEX_FAISS = "index-faiss"
SUBCOMMAND_API = "api"
SUBCOMMAND_E2E = "e2e"

CLI_PROBLEM_TYPE_BASE = "https://kgfoundry.dev/problems/orchestration"

STATUS_NOT_FOUND = 404
STATUS_BAD_REQUEST = 400
STATUS_UNPROCESSABLE_ENTITY = 422
STATUS_INTERNAL_ERROR = 500
STATUS_CLIENT_CLOSED = 499
STATUS_MIN_CLIENT_ERROR = 400
STATUS_MAX_CLIENT_ERROR = 499

_e2e_flow: Callable[[], list[str]] | None = None
with contextlib.suppress(ImportError):
    from orchestration.flows import e2e_flow as _loaded_flow

    _e2e_flow = _loaded_flow


def _resolve_cli_help() -> str:
    """Resolve the CLI help text from configuration and settings.

    This function constructs the help text displayed when users request CLI
    help (--help flag). The help text combines the CLI title from configuration
    with the version from settings, providing users with clear identification
    of the CLI tool and its version.

    Returns
    -------
    str
        Help text string combining CLI title and version. Format: "{title} ({version})".
        The title comes from CLI_CONFIG or defaults to CLI_TITLE, while version
        comes from CLI_SETTINGS.

    Notes
    -----
    CLI help text is the first thing users see when exploring the command-line
    interface. Including version information helps users understand which version
    of the tool they're using and enables troubleshooting of version-specific
    issues. The help text is used by Typer to generate command help output.
    """
    title = CLI_CONFIG.title or CLI_TITLE
    return f"{title} ({CLI_SETTINGS.version})"


app = typer.Typer(help=_resolve_cli_help(), no_args_is_help=True, add_completion=False)
_DEFAULT_CONTEXT = OrchestrationCliContext.production()


def _default_artifact_dir() -> Path:
    """Determine the default directory for CLI-generated artifacts.

    This function returns the default base directory where CLI commands write
    artifacts such as indexes, vectors, and other generated files. The directory
    is relative to the current working directory, making it suitable for local
    development and testing.

    Returns
    -------
    Path
        Default artifact directory path. The path points to "./_indices" relative
        to the current working directory, providing a standard location for all
        CLI-generated artifacts.

    Notes
    -----
    Artifact directories provide a consistent location for CLI-generated files,
    enabling predictable artifact discovery and cleanup. The default location
    can be overridden via command-line options, allowing users to specify custom
    artifact locations for different environments or use cases.
    """
    return Path("./_indices")


def _store_cli_state(
    ctx: typer.Context,
    envelope_dir: Path | None,
    artifact_dir: Path | None,
) -> None:
    """Store CLI state in Typer context for command execution.

    This function persists command-line options (envelope directory and artifact
    directory) in the Typer context object, making them available to all
    subcommands during command execution. The state is stored as a dictionary
    attached to the context, enabling shared configuration across command
    invocations.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object that stores command state. The context is shared
        across all subcommands in a command invocation, enabling state sharing.
    envelope_dir : Path | None
        Optional envelope directory path from command-line options. If provided,
        overrides the default envelope directory for this command execution.
    artifact_dir : Path | None
        Optional artifact directory path from command-line options. If provided,
        overrides the default artifact directory for this command execution.

    Notes
    -----
    CLI state storage enables command-line options to be shared across subcommands
    without requiring explicit parameter passing. The state is stored in the Typer
    context object, which is accessible to all commands via ctx.obj. This pattern
    enables clean separation between option parsing (in callbacks) and option
    usage (in commands).
    """
    state = ctx.ensure_object(dict)
    state["envelope_dir"] = envelope_dir
    state["artifact_dir"] = artifact_dir


def _resolve_envelope_dir(ctx: typer.Context | None) -> Path:
    """Resolve envelope directory from context or return default.

    This function determines the envelope directory to use for command execution
    by checking the Typer context for stored state. If no context is provided or
    no envelope directory is stored, the function returns the default envelope
    directory. This enables commands to use custom envelope directories specified
    via command-line options while falling back to sensible defaults.

    Parameters
    ----------
    ctx : typer.Context | None
        Optional Typer context containing stored CLI state. If provided and
        contains an envelope_dir entry, that value is used. Otherwise, the
        default directory is returned.

    Returns
    -------
    Path
        Resolved envelope directory path. Either the directory from context state
        (if provided) or the default envelope directory. The path is guaranteed
        to be a Path object ready for filesystem operations.

    Notes
    -----
    Envelope directory resolution enables flexible configuration of where CLI
    envelopes are written. Commands can override the default location via
    command-line options, enabling integration with different build systems
    and CI/CD pipelines. The function handles None contexts gracefully for
    testing and programmatic invocation.
    """
    default_dir = _default_envelope_dir()
    if ctx is None or ctx.obj is None:
        return default_dir
    state = ctx.ensure_object(dict)
    directory = state.get("envelope_dir")
    if directory is None:
        return default_dir
    return Path(directory)


def _resolve_artifact_dir(ctx: typer.Context | None) -> Path:
    """Resolve artifact directory from context or return default.

    This function determines the artifact directory to use for command execution
    by checking the Typer context for stored state. If no context is provided or
    no artifact directory is stored, the function returns the default artifact
    directory. This enables commands to use custom artifact directories specified
    via command-line options while falling back to sensible defaults.

    Parameters
    ----------
    ctx : typer.Context | None
        Optional Typer context containing stored CLI state. If provided and
        contains an artifact_dir entry, that value is used. Otherwise, the
        default directory is returned.

    Returns
    -------
    Path
        Resolved artifact directory path. Either the directory from context state
        (if provided) or the default artifact directory. The path is guaranteed
        to be a Path object ready for filesystem operations.

    Notes
    -----
    Artifact directory resolution enables flexible configuration of where CLI
    artifacts (indexes, vectors, etc.) are written. Commands can override the
    default location via command-line options, enabling integration with different
    build systems and deployment environments. The function handles None contexts
    gracefully for testing and programmatic invocation.
    """
    default_dir = _default_artifact_dir()
    if ctx is None or ctx.obj is None:
        return default_dir
    state = ctx.ensure_object(dict)
    directory = state.get("artifact_dir")
    if directory is None:
        return default_dir
    return Path(directory)


def _cli_context(ctx: typer.Context | None = None) -> OrchestrationCliContext:
    """Retrieve or create orchestration CLI context from Typer context.

    This function retrieves the OrchestrationCliContext from the Typer context
    state, creating and caching it if it doesn't exist. The context provides
    dependency injection for CLI commands, enabling testing with mock factories
    and providers. The function handles both explicit context passing and
    implicit context retrieval from Click's current context.

    Parameters
    ----------
    ctx : typer.Context | None, optional
        Optional Typer context to retrieve context from. If None, attempts to
        retrieve the current Click context using click.get_current_context.
        If no context is available, returns the default production context.

    Returns
    -------
    OrchestrationCliContext
        CLI context object containing factories and providers for command execution.
        The context is cached in the Typer context state after first creation,
        ensuring consistent context usage across a command invocation.

    Notes
    -----
    CLI context retrieval enables dependency injection for CLI commands, allowing
    commands to use configurable factories for BM25 builders, FAISS runners, and
    artifact filesystems. The context is cached in the Typer context state to
    avoid repeated creation and ensure consistent behavior throughout command
    execution. The function gracefully handles missing contexts by returning
    the default production context.
    """
    active = ctx or click.get_current_context(silent=True)
    if active is None:
        return _DEFAULT_CONTEXT
    state = active.ensure_object(dict)
    context = state.get("orchestration_cli_context")
    if isinstance(context, OrchestrationCliContext):
        return context
    state["orchestration_cli_context"] = _DEFAULT_CONTEXT
    return _DEFAULT_CONTEXT


@app.callback()
def orchestration_callback(
    ctx: typer.Context,
    envelope_dir: _EnvelopeDirOption = None,
    artifact_dir: _ArtifactDirOption = None,
) -> None:
    """Configure shared orchestration CLI options."""
    _store_cli_state(ctx, envelope_dir, artifact_dir)
    state = ctx.ensure_object(dict)
    state.setdefault("orchestration_cli_context", _DEFAULT_CONTEXT)


def _coerce_extension_value(value: object) -> JsonValue:
    """Recursively coerce a value to JSON-serializable types for Problem Details extensions.

    This function converts arbitrary Python objects into JSON-serializable values
    suitable for inclusion in RFC 9457 Problem Details extension dictionaries.
    The function handles primitive types (str, int, float, bool, None), sequences
    (lists), mappings (dicts), and falls back to string conversion for other types.
    Recursive coercion ensures nested structures are properly serialized.

    Parameters
    ----------
    value : object
        Value to coerce to JSON-serializable form. May be any Python object,
        including nested structures like lists and dictionaries.

    Returns
    -------
    JsonValue
        JSON-serializable value (str, int, float, bool, None, list, or dict).
        Nested structures are recursively coerced, and non-serializable types
        are converted to strings.

    Notes
    -----
    Problem Details extensions require JSON-serializable values, but Python code
    often works with richer types. This function bridges that gap by converting
    values to JSON-compatible forms while preserving structure. Recursive coercion
    ensures that nested dictionaries and lists are properly handled, enabling
    complex extension data to be included in Problem Details payloads.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(map(_coerce_extension_value, value))
    if isinstance(value, Mapping):
        return {str(key): _coerce_extension_value(val) for key, val in value.items()}
    return str(value)


def _log_cli_event(
    level: int,
    message: str,
    context: _CommandContext,
    **fields: object,
) -> None:
    """Emit structured log events with correlation metadata."""
    operation_name = context.subcommand.replace("-", "_")
    payload: dict[str, object] = {
        "operation": operation_name,
        "subcommand": context.subcommand,
        "operation_id": context.operation_id,
        "correlation_id": context.correlation_id,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    LOGGER.log(level, message, extra=payload)


def _start_command(
    ctx: typer.Context,
    subcommand: str,
    **log_fields: object,
) -> tuple[_CommandContext, CliEnvelopeBuilder]:
    """Initialize command execution context and envelope builder.

    This function sets up the execution context for a CLI command by creating
    operation and correlation IDs, initializing the envelope builder, and
    logging the command start. The function generates unique identifiers for
    tracking command execution and creates a structured context object that
    carries metadata throughout command execution.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state. Used to resolve envelope
        directory and retrieve CLI context for UUID generation.
    subcommand : str
        Subcommand name (e.g., "index-bm25", "index-faiss") identifying the
        command being executed. Used for operation ID lookup and logging.
    **log_fields : object
        Additional keyword arguments to include in start logging. Fields with
        None values are filtered out before logging. Used to log command-specific
        parameters like file paths, configuration values, etc.

    Returns
    -------
    tuple[_CommandContext, CliEnvelopeBuilder]
        Tuple containing:
        - Command context object with operation ID, correlation ID, start time,
          and envelope directory. The context is used throughout command execution
          for logging and error handling.
        - Envelope builder initialized for the command. The builder is used to
          construct the CLI envelope that captures command execution metadata.

    Notes
    -----
    Command initialization sets up the infrastructure for structured command
    execution, including unique identifiers for tracking, envelope building
    for artifact generation, and logging for observability. The function ensures
    all commands have consistent initialization, enabling uniform error handling
    and result reporting across the CLI.
    """
    orchestration_context = _cli_context(ctx)
    operation_id = CLI_OPERATION_IDS.get(subcommand, subcommand)
    correlation_id = orchestration_context.uuid_factory()
    filtered_fields = {key: value for key, value in log_fields.items() if value is not None}
    if filtered_fields:
        typer.echo(
            f"Starting {subcommand} with "
            + ", ".join(f"{key}={value}" for key, value in filtered_fields.items())
        )
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND, status="success", subcommand=subcommand
    )
    context = _CommandContext(
        subcommand=subcommand,
        operation_id=operation_id,
        correlation_id=correlation_id,
        start=time.monotonic(),
        envelope_dir=_resolve_envelope_dir(ctx),
    )
    _log_cli_event(
        logging.INFO,
        f"{subcommand} starting",
        context,
        status="starting",
        metadata=filtered_fields or None,
    )
    return context, builder


def _run_status_from_error(error_status: CliErrorStatus) -> CliStatus:
    """Map CLI error status to run status for envelope reporting.

    This function converts CLI error status values (which indicate error categories)
    to run status values (which indicate overall command outcome). The mapping
    preserves specific error statuses ("config", "violation") as run statuses
    when they provide useful categorization, and maps other error statuses to
    the generic "error" run status.

    Parameters
    ----------
    error_status : CliErrorStatus
        CLI error status indicating the category of error that occurred. Valid
        values include "config" (configuration errors), "violation" (validation
        errors), and "error" (general errors).

    Returns
    -------
    CliStatus
        Run status value for envelope reporting. Returns the error_status if it's
        "config" or "violation", otherwise returns "error". The run status indicates
        the overall command outcome for envelope metadata.

    Notes
    -----
    Error status mapping enables fine-grained error categorization in CLI envelopes
    while maintaining a simpler run status for overall command outcome. Specific
    error statuses like "config" and "violation" provide useful categorization
    for downstream tooling, while generic errors are mapped to "error" for
    consistency.
    """
    return cast(
        "CliStatus",
        error_status if error_status in {"config", "violation"} else "error",
    )


def _error_status_from_http(status: int) -> CliErrorStatus:
    """Map HTTP status code to CLI error status for Problem Details.

    This function converts HTTP status codes to CLI error status values that
    categorize errors for Problem Details reporting. The mapping follows HTTP
    status code semantics: 422 (Unprocessable Entity) maps to "violation"
    (validation errors), 4xx client errors map to "config" (configuration errors),
    and other errors map to "error" (general errors).

    Parameters
    ----------
    status : int
        HTTP status code from error handling. Status codes are interpreted
        according to HTTP semantics: 422 indicates validation errors, 4xx
        indicates client errors (configuration), and other codes indicate
        server errors.

    Returns
    -------
    CliErrorStatus
        CLI error status value ("violation", "config", or "error") corresponding
        to the HTTP status code. The error status is used in Problem Details
        and CLI envelopes to categorize errors for downstream tooling.

    Notes
    -----
    HTTP status code mapping enables consistent error categorization across
    different error sources. The function follows HTTP semantics where 4xx
    codes indicate client errors (often configuration-related) and 5xx codes
    indicate server errors. Status 422 specifically indicates validation
    violations, enabling precise error categorization.
    """
    if status == STATUS_UNPROCESSABLE_ENTITY:
        return cast("CliErrorStatus", "violation")
    if (
        status in {STATUS_BAD_REQUEST, STATUS_NOT_FOUND, STATUS_CLIENT_CLOSED}
        or STATUS_MIN_CLIENT_ERROR <= status <= STATUS_MAX_CLIENT_ERROR
    ):
        return cast("CliErrorStatus", "config")
    return cast("CliErrorStatus", "error")


def _problem_type_for(subcommand: str) -> str:
    """Generate Problem Details type URI for a subcommand.

    This function constructs a Problem Details type URI by combining the base
    problem type URI with a sanitized subcommand name. The URI follows RFC 9457
    Problem Details format and enables unique identification of error types
    for different subcommands. Subcommand names are sanitized to ensure valid
    URI construction.

    Parameters
    ----------
    subcommand : str
        Subcommand name (e.g., "index-bm25", "index-faiss") to generate a problem
        type for. The subcommand name is sanitized by replacing "/" with "-" to
        ensure valid URI construction.

    Returns
    -------
    str
        Problem Details type URI string. Format: "{base}/{sanitized_subcommand}".
        The URI uniquely identifies error types for the subcommand, enabling
        downstream tooling to handle errors appropriately.

    Notes
    -----
    Problem Details type URIs enable unique identification of error types across
    different subcommands and systems. The URI format follows RFC 9457 conventions
    and provides a namespace for error types. Sanitization ensures that subcommand
    names with special characters (like "/") produce valid URIs.
    """
    safe = subcommand.replace("/", "-")
    return f"{CLI_PROBLEM_TYPE_BASE}/{safe}"


def _build_cli_problem(
    context: _CommandContext,
    *,
    detail: str,
    status: int,
    extras: Mapping[str, object] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> ProblemDetailsDict:
    """Build RFC 9457 Problem Details dictionary for CLI command failures.

    This function constructs a Problem Details dictionary following RFC 9457
    format, including type, title, status, detail, instance, and extensions.
    The problem details provide structured error information suitable for
    machine-readable error handling and user-facing error messages.

    Parameters
    ----------
    context : _CommandContext
        Command execution context containing subcommand, operation ID, and
        correlation ID. Used to generate problem type, title, instance URI,
        and extension metadata.
    detail : str
        Human-readable error detail message describing what went wrong. The
        detail should be specific enough to help users understand and resolve
        the error.
    status : int
        HTTP status code indicating the error category. Used to determine
        appropriate error categorization and user messaging.
    extras : Mapping[str, object] | None, optional
        Additional key-value pairs to include in the extensions dictionary.
        Extras are coerced to JSON-serializable values and merged with
        context extensions (operation_id, correlation_id).
    overrides : Mapping[str, str] | None, optional
        Optional overrides for problem type and title. If provided, these
        values take precedence over generated values, enabling custom error
        types and messages.

    Returns
    -------
    ProblemDetailsDict
        Complete Problem Details dictionary following RFC 9457 format. Includes
        type, title, status, detail, instance, and extensions fields. The
        dictionary is ready for JSON serialization and inclusion in CLI
        envelopes and HTTP error responses.

    Notes
    -----
    Problem Details construction enables structured error reporting that is
    both human-readable and machine-processable. The function generates
    consistent error structures across all CLI commands, enabling uniform
    error handling and user experience. Extensions provide additional context
    for debugging and error analysis.
    """
    override_title = overrides.get("title") if overrides else None
    override_type = overrides.get("type") if overrides else None
    return build_problem_details(
        ProblemDetailsParams(
            type=override_type or _problem_type_for(context.subcommand),
            title=override_title
            or f"{CLI_TITLE} {context.subcommand.replace('-', ' ')} command failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_INTERFACE_ID}:{context.subcommand}",
            extensions=context.extensions(extras),
        )
    )


def _envelope_path(subcommand: str, *, envelope_dir: Path) -> Path:
    """Generate file path for CLI envelope output.

    This function constructs the file path where a CLI envelope should be written
    based on the subcommand name and envelope directory. The filename includes
    the binary name, CLI command name, and sanitized subcommand name, ensuring
    unique filenames for different commands while maintaining a predictable
    naming convention.

    Parameters
    ----------
    subcommand : str
        Subcommand name (e.g., "index-bm25", "index-faiss") to generate a path
        for. The subcommand name is sanitized by replacing "/" with "-" to ensure
        valid filename construction. Empty strings are treated as "root".
    envelope_dir : Path
        Directory where the envelope file should be written. The directory is
        used as the parent directory for the generated filename.

    Returns
    -------
    Path
        Complete file path for the CLI envelope. The path combines the envelope
        directory with a generated filename that includes binary name, command
        name, and subcommand name. The filename uses .json extension.

    Notes
    -----
    Envelope path generation ensures consistent naming of CLI execution artifacts
    across different commands and environments. The naming convention includes
    enough information to uniquely identify envelopes while remaining human-readable.
    Filename sanitization ensures that subcommand names with special characters
    produce valid filenames.
    """
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand.replace('/', '-')}.json"
    return envelope_dir / filename


def _emit_envelope(envelope: CliEnvelope, *, subcommand: str, envelope_dir: Path) -> Path:
    """Write CLI envelope to disk and return the file path.

    This function persists a CLI envelope to disk by generating the envelope path,
    ensuring the directory exists, rendering the envelope to JSON, and writing
    it to the file. The envelope captures command execution metadata including
    status, duration, files, errors, and problem details.

    Parameters
    ----------
    envelope : CliEnvelope
        Complete CLI envelope object containing command execution metadata. The
        envelope includes status, duration, files processed, errors encountered,
        and problem details for failures.
    subcommand : str
        Subcommand name used to generate the envelope filename. The subcommand
        name is sanitized and included in the filename for identification.
    envelope_dir : Path
        Directory where the envelope file should be written. The directory is
        created if it doesn't exist, including all parent directories.

    Returns
    -------
    Path
        File path where the envelope was written. The path can be used for
        logging, user messaging, and downstream tooling integration.

    Notes
    -----
    Envelope emission enables structured output from CLI commands, providing
    machine-readable metadata about command execution. The envelopes are written
    as JSON files following a consistent format, enabling integration with build
    systems, CI/CD pipelines, and monitoring tools. The function ensures
    directories exist before writing to prevent errors.
    """
    path = _envelope_path(subcommand, envelope_dir=envelope_dir)
    envelope_dir.mkdir(parents=True, exist_ok=True)
    payload = render_cli_envelope(envelope)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def _finish_success(context: _CommandContext, builder: CliEnvelopeBuilder) -> CliEnvelope:
    """Complete successful command execution and emit envelope.

    This function finalizes successful command execution by computing duration,
    finishing the envelope builder, emitting the envelope to disk, and logging
    completion. The function provides user feedback via console output and
    structured logging, ensuring users know the command completed successfully
    and where the envelope was written.

    Parameters
    ----------
    context : _CommandContext
        Command execution context containing start time, subcommand, and envelope
        directory. The start time is used to compute execution duration.
    builder : CliEnvelopeBuilder
        Envelope builder that has been populated with command execution metadata
        (files processed, status updates, etc.). The builder is finished with
        the computed duration.

    Returns
    -------
    CliEnvelope
        Completed CLI envelope containing all execution metadata. The envelope
        includes status="success", duration, files processed, and other metadata
        captured during command execution.

    Notes
    -----
    Success completion ensures consistent handling of successful command execution
    across all CLI commands. The function computes duration from the context start
    time, finishes the envelope with success status, emits it to disk, and logs
    completion. This provides both user feedback and structured metadata for
    downstream tooling.
    """
    envelope = builder.finish(duration_seconds=time.monotonic() - context.start)
    path = _emit_envelope(
        envelope,
        subcommand=context.subcommand,
        envelope_dir=context.envelope_dir,
    )
    typer.echo(
        f"{context.subcommand} completed in {envelope.duration_seconds:.2f}s (envelope: {path})"
    )
    _log_cli_event(
        logging.INFO,
        f"{context.subcommand} completed",
        context,
        status="success",
        duration=envelope.duration_seconds,
        envelope=str(path),
    )
    return envelope


def _handle_failure(
    context: _CommandContext, *, detail: str, status: int, **options: object
) -> None:
    """Handle command execution failure and emit error envelope.

    This function processes command failures by building Problem Details, creating
    an error envelope, emitting it to disk, and providing user feedback. The
    function handles error categorization, envelope construction, and structured
    error reporting following RFC 9457 Problem Details format.

    Parameters
    ----------
    context : _CommandContext
        Command execution context containing subcommand, operation ID, correlation
        ID, and start time. Used for Problem Details construction and logging.
    detail : str
        Human-readable error detail message describing what went wrong. The
        detail is included in Problem Details and displayed to users.
    status : int
        HTTP status code indicating the error category. Used to determine error
        status mapping and Problem Details construction.
    **options : object
        Optional keyword arguments for error handling:
        - error_status: CliErrorStatus to use instead of deriving from HTTP status
        - extras: Mapping[str, object] of additional Problem Details extensions
        - overrides: Mapping[str, str] of Problem Details type/title overrides
        - exc: BaseException that caused the failure, displayed to users

    Notes
    -----
    Failure handling ensures consistent error reporting across all CLI commands.
    The function builds Problem Details following RFC 9457, creates an error
    envelope with failure status, emits it to disk, and provides comprehensive
    user feedback including error messages, exception details, and Problem Details
    JSON. This enables both human-readable error messages and machine-processable
    error metadata for downstream tooling.
    """
    error_status_option = cast("CliErrorStatus | None", options.get("error_status"))
    extras = cast("Mapping[str, object] | None", options.get("extras"))
    overrides = cast("Mapping[str, str] | None", options.get("overrides"))
    exc = cast("BaseException | None", options.get("exc"))

    cli_error_status: CliErrorStatus = error_status_option or _error_status_from_http(status)
    cli_run_status: CliStatus = _run_status_from_error(cli_error_status)
    problem_payload = _build_cli_problem(
        context,
        detail=detail,
        status=status,
        extras=extras,
        overrides=overrides,
    )
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND, status=cli_run_status, subcommand=context.subcommand
    )
    builder = builder.add_error(status=cli_error_status, message=detail, problem=problem_payload)
    builder = builder.set_problem(problem_payload)
    envelope = builder.finish(duration_seconds=time.monotonic() - context.start)
    path = _emit_envelope(
        envelope,
        subcommand=context.subcommand,
        envelope_dir=context.envelope_dir,
    )
    typer.echo(
        f"{context.subcommand} failed ({cli_run_status}); envelope: {path}",
        err=True,
    )
    if exc is not None:
        typer.echo(str(exc), err=True)
    typer.echo(json.dumps(problem_payload, sort_keys=True), err=True)
    typer.echo(detail, err=True)
    _log_cli_event(
        logging.ERROR,
        detail,
        context,
        status="failure",
        cli_status=cli_run_status,
        http_status=status,
        envelope=str(path),
        problem=problem_payload,
    )


def _extract_bm25_document(
    record: Mapping[str, object],
) -> tuple[str, dict[str, str]] | None:
    """Extract BM25 document tuple from a chunk record mapping.

    This function extracts document metadata from a chunk record dictionary,
    converting it into the format required by BM25 index builders. The function
    validates that chunk_id exists and is a string, and extracts title, section,
    and text fields with type coercion and default values.

    Parameters
    ----------
    record : Mapping[str, object]
        Chunk record dictionary containing chunk_id, title, section, and text
        fields. The record may have missing or non-string values, which are
        handled with defaults.

    Returns
    -------
    tuple[str, dict[str, str]] | None
        Document tuple containing (chunk_id, metadata_dict) if chunk_id is
        present and is a string, or None if chunk_id is missing or invalid.
        The metadata dictionary contains "title", "section", and "body" (from
        "text") fields, with empty strings as defaults for missing values.

    Notes
    -----
    Document extraction enables BM25 index construction from heterogeneous chunk
    datasets. The function handles missing fields gracefully by providing defaults,
    ensuring robust processing of incomplete or inconsistent data. Type coercion
    ensures that non-string values are converted to strings or replaced with
    empty strings, preventing type errors during indexing.
    """
    chunk_id = record.get("chunk_id")
    if not isinstance(chunk_id, str):
        return None
    title_raw = record.get("title")
    section_raw = record.get("section")
    text_raw = record.get("text")
    title = title_raw if isinstance(title_raw, str) else ""
    section = section_raw if isinstance(section_raw, str) else ""
    text = text_raw if isinstance(text_raw, str) else ""
    return chunk_id, {"title": title, "section": section, "body": text}


def _load_bm25_documents(chunks_path: str) -> list[tuple[str, dict[str, str]]]:
    """Load BM25 documents from JSON or JSONL file.

    This function loads chunk documents from either a JSON array file or a JSONL
    (JSON Lines) file, extracting BM25-compatible document tuples. The function
    handles both formats automatically based on file extension, parsing each
    record and extracting valid documents using _extract_bm25_document.

    Parameters
    ----------
    chunks_path : str
        Path to JSON or JSONL file containing chunk records. JSON files should
        contain an array of mapping objects, while JSONL files contain one
        JSON object per line.

    Returns
    -------
    list[tuple[str, dict[str, str]]]
        List of document tuples ready for BM25 indexing. Each tuple contains
        (chunk_id, metadata_dict) with title, section, and body fields. Invalid
        records are silently skipped.

    Raises
    ------
    TypeError
        Raised when the JSON file does not contain a sequence of mapping objects.
        This indicates malformed input data that cannot be processed.

    Notes
    -----
    Document loading supports both JSON array and JSONL formats, enabling flexible
    input data sources. The function handles malformed JSON lines gracefully by
    skipping them, ensuring robust processing of large datasets. Invalid records
    (missing chunk_id or wrong types) are filtered out during extraction.
    """
    docs: list[tuple[str, dict[str, str]]] = []
    path = Path(chunks_path)
    if chunks_path.endswith(".jsonl"):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload: object = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, Mapping) and (document := _extract_bm25_document(payload)):
                    docs.append(document)
    else:
        with path.open("r", encoding="utf-8") as handle:
            payload: object = json.load(handle)
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            msg = "Chunk dataset must be a sequence of mapping objects"
            raise TypeError(msg)
        docs.extend(
            document
            for entry in payload
            if isinstance(entry, Mapping) and (document := _extract_bm25_document(entry))
        )
    return docs


def _get_bm25_index_path(index_dir: Path, backend: str) -> Path:
    """Determine the file path for a BM25 index based on backend type.

    This function generates the appropriate file path for a BM25 index depending
    on the backend used. Pure Python backends store indexes as pickle files,
    while Lucene backends store indexes as directories. The function enables
    consistent index path resolution across different backend implementations.

    Parameters
    ----------
    index_dir : Path
        Base directory where the BM25 index should be stored. The index path
        is constructed relative to this directory.
    backend : str
        Backend name ("pure" or "lucene") determining the index format and
        filename. Pure backends use "pure_bm25.pkl", while Lucene backends
        use "bm25_index" directory.

    Returns
    -------
    Path
        Complete file path for the BM25 index. For pure backends, this is a
        .pkl file path. For Lucene backends, this is a directory path where
        the Lucene index is stored.

    Notes
    -----
    Index path resolution enables consistent index storage across different
    backend implementations. The function abstracts backend-specific path
    conventions, allowing code to work with indexes regardless of backend
    type. This simplifies index management and enables backend switching
    without code changes.
    """
    return index_dir / "pure_bm25.pkl" if backend == "pure" else index_dir / "bm25_index"


def _instantiate_bm25_builder(config: BM25BuildConfig) -> tuple[_BM25Builder, str]:
    """Create and configure a BM25 builder instance with fallback handling.

    This function instantiates a BM25 builder using the requested backend from
    configuration, with automatic fallback to pure Python backend if Lucene is
    unavailable. The function handles backend initialization errors gracefully,
    ensuring robust index construction even when optional dependencies are missing.

    Parameters
    ----------
    config : BM25BuildConfig
        Configuration specifying the requested backend and index directory.
        The backend name is normalized (lowercased, stripped) before lookup.

    Returns
    -------
    tuple[_BM25Builder, str]
        Tuple containing:
        - BM25 builder instance configured with k1=0.9, b=0.4, and load_existing=False.
        - Backend name actually used (may differ from requested if fallback occurs).

    Raises
    ------
    RuntimeError
        Raised when backend initialization fails and the requested backend is
        not "lucene" (no fallback available). For Lucene backends, fallback
        to pure backend is attempted automatically.

    Notes
    -----
    Builder instantiation enables flexible BM25 backend selection with graceful
    degradation. The function attempts to use the requested backend first,
    falling back to pure Python backend if Lucene is unavailable. This ensures
    robust index construction even when optional dependencies are missing, while
    providing user feedback about backend selection.
    """
    requested_backend = config.backend.strip().lower()
    try:
        builder = cast(
            "_BM25Builder",
            get_bm25(requested_backend, config.index_dir, k1=0.9, b=0.4, load_existing=False),
        )
    except RuntimeError:
        if requested_backend != "lucene":
            raise
        typer.echo("Lucene backend unavailable; using pure backend", err=True)
        fallback = cast(
            "_BM25Builder",
            get_bm25("pure", config.index_dir, k1=0.9, b=0.4, load_existing=False),
        )
        return fallback, "pure"
    return builder, requested_backend


def _build_bm25_index(
    config: BM25BuildConfig,
    *,
    logger: logging.Logger | None = None,
) -> tuple[str, int]:
    """Build a BM25 index from chunk documents with error handling and fallback.

    This function orchestrates BM25 index construction by loading documents,
    instantiating a builder, and building the index. The function handles
    backend failures with automatic fallback to pure Python backend, ensuring
    robust index construction even when Lucene is unavailable or fails.

    Parameters
    ----------
    config : BM25BuildConfig
        Configuration specifying chunks path, backend type, and index directory.
        The configuration determines document source, backend selection, and
        index storage location.
    logger : logging.Logger | None, optional
        Optional logger for recording build progress. If None, uses the module
        LOGGER. Used to emit structured log events during index construction.

    Returns
    -------
    tuple[str, int]
        Tuple containing:
        - Backend name actually used for construction (may differ from requested
          if fallback occurred, e.g., "lucene" -> "pure").
        - Number of documents successfully indexed.

    Raises
    ------
    RuntimeError
        Raised when index construction fails and fallback is not possible.
        Includes original exception as cause for debugging. Also raised for
        non-Lucene backend failures where fallback is not applicable.

    Notes
    -----
    Index construction handles backend failures gracefully by attempting fallback
    to pure Python backend when Lucene fails. This ensures robust index building
    even when optional dependencies are unavailable or misconfigured. The function
    logs build progress and provides user feedback about backend selection and
    document counts.

    May propagate ``AttributeError``, ``ValueError``, or ``KeyError`` from
    builder instantiation or document loading when builder API is incompatible,
    configuration is invalid, or required keys are missing. These exceptions
    are re-raised with context to preserve error information.
    """
    documents = _load_bm25_documents(config.chunks_path)
    builder, backend_used = _instantiate_bm25_builder(config)
    log = logger or LOGGER
    try:
        builder.build(documents)
        log.info("bm25-build", extra={"documents": len(documents), "backend": backend_used})
    except RuntimeError:
        if backend_used != "lucene":
            raise
        typer.echo("Lucene build failed; retrying with pure backend", err=True)
        fallback_builder = cast(
            "_BM25Builder",
            get_bm25("pure", config.index_dir, k1=0.9, b=0.4, load_existing=False),
        )
        fallback_builder.build(documents)
        backend_used = "pure"
    except (AttributeError, ValueError, KeyError) as exc:
        msg = f"Failed to build BM25 index: {exc}"
        raise RuntimeError(msg) from exc
    return backend_used, len(documents)


_VECTOR_SCHEMA_PATH = cli_context.REPO_ROOT / "schema/vector-ingestion/vector-batch.v1.schema.json"
_VECTOR_SCHEMA_ID = "https://kgfoundry.dev/schema/vector-ingestion/vector-batch.v1.json"
_VECTOR_PROBLEM_TYPE = "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
_VECTOR_SCHEMA_ERROR_LIMIT = 5
_VECTOR_VALIDATOR_CACHE: dict[str, Draft202012ValidatorProtocol] = {}


def _vector_batch_validator() -> Draft202012ValidatorProtocol:
    """Get or create cached JSON Schema validator for vector batch payloads.

    This function retrieves a cached JSON Schema validator for vector batch
    payloads, creating it on first call and caching it for subsequent use.
    The validator is constructed from the vector batch schema file and uses
    JSON Schema Draft 2020-12 for validation.

    Returns
    -------
    Draft202012ValidatorProtocol
        JSON Schema validator instance ready for validating vector batch payloads.
        The validator checks payload structure against the vector batch schema,
        ensuring compliance with expected format and data types.

    Notes
    -----
    Validator caching improves performance by avoiding repeated schema loading
    and validator construction. The validator is created once and reused across
    all validation operations, reducing overhead for batch processing. The
    validator uses JSON Schema Draft 2020-12, providing comprehensive validation
    capabilities for complex nested structures.
    """
    validator = _VECTOR_VALIDATOR_CACHE.get("validator")
    if validator is None:
        schema = load_schema(_VECTOR_SCHEMA_PATH)
        validator = create_draft202012_validator(cast("dict[str, object]", schema))
        _VECTOR_VALIDATOR_CACHE["validator"] = validator
    return validator


def _error_sort_key(error: ValidationErrorProtocol) -> tuple[str, ...]:
    """Generate sort key for validation errors based on error path.

    This function creates a sort key for validation errors by converting the
    error path to a tuple of strings. The sort key enables consistent ordering
    of validation errors by their location in the payload structure, making
    error messages more readable and predictable.

    Parameters
    ----------
    error : ValidationErrorProtocol
        Validation error object containing a path attribute describing where
        the error occurred in the payload structure. The path is typically a
        sequence of path components (field names, indices, etc.).

    Returns
    -------
    tuple[str, ...]
        Sort key tuple containing string representations of error path components.
        The tuple enables lexicographic sorting of errors by their location in
        the payload, ensuring consistent error ordering.

    Notes
    -----
    Error sorting improves user experience by presenting validation errors in
    a consistent, predictable order. Errors are sorted by their location in
    the payload structure, making it easier to identify and fix validation
    issues. The tuple-based sort key enables efficient sorting of large error
    lists.
    """
    return tuple(str(part) for part in error.path)


def _validate_vector_payload(payload: object) -> None:
    """Validate vector batch payload against JSON Schema with detailed error reporting.

    This function validates a vector batch payload against the vector batch schema
    using JSON Schema Draft 2020-12. The function collects validation errors,
    sorts them by path, and raises a VectorValidationError with detailed error
    messages if validation fails. Error messages are limited to prevent overwhelming
    output while providing enough detail for debugging.

    Parameters
    ----------
    payload : object
        Vector batch payload to validate. The payload should be a sequence of
        mapping objects containing vector data. The payload structure is validated
        against the vector batch schema.

    Raises
    ------
    VectorValidationError
        Raised when validation fails. The exception includes a primary error message
        and a list of detailed error messages describing all validation failures.
        Error messages are limited to _VECTOR_SCHEMA_ERROR_LIMIT to prevent
        overwhelming output, with a summary message if more errors exist.

    Notes
    -----
    Payload validation ensures that vector batch data conforms to the expected
    schema before processing, preventing errors during index construction. The
    function provides detailed error messages sorted by error location, making
    it easier to identify and fix validation issues. Error limiting prevents
    overwhelming output while preserving enough detail for debugging.
    """
    validator = _vector_batch_validator()
    errors = sorted(validator.iter_errors(payload), key=_error_sort_key)
    if not errors:
        return
    messages: list[str] = []
    for error in errors[:_VECTOR_SCHEMA_ERROR_LIMIT]:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    if len(errors) > _VECTOR_SCHEMA_ERROR_LIMIT:
        remaining = len(errors) - _VECTOR_SCHEMA_ERROR_LIMIT
        messages.append(f"... {remaining} additional validation errors")
    raise VectorValidationError(messages[0], errors=messages)


def load_vector_batch_from_json(vectors_path: str) -> VectorBatch:
    """Load and validate a vector batch from a JSON file.

    Parameters
    ----------
    vectors_path : str
        Path to JSON file containing vector batch data.

    Returns
    -------
    VectorBatch
        Validated vector batch object.

    Raises
    ------
    FileNotFoundError
        If the vectors file does not exist.
    VectorValidationError
        If the payload structure is invalid or fails validation.
    """
    vectors_file = Path(vectors_path)
    if not vectors_file.exists():
        msg = f"Vectors file not found: {vectors_path}"
        raise FileNotFoundError(msg)
    with vectors_file.open("r", encoding="utf-8") as handle:
        payload: object = json.load(handle)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        msg = "Dense vectors payload must be a sequence of mapping objects"
        raise VectorValidationError(msg, errors=[msg])
    _validate_vector_payload(payload)
    records = cast("Iterable[Mapping[str, object]]", payload)
    return coerce_vector_batch(records)


def _prepare_index_directory(index_path: str) -> None:
    """Ensure the parent directory of an index path exists.

    This function creates the parent directory of an index file path, including
    all necessary parent directories. The function is idempotent, succeeding
    even if the directory already exists, ensuring safe preparation of index
    storage locations.

    Parameters
    ----------
    index_path : str
        File path where an index will be written. The function creates the
        parent directory of this path, ensuring the directory structure exists
        before index writing.

    Notes
    -----
    Directory preparation prevents errors during index writing by ensuring
    parent directories exist before file operations. The function uses pathlib's
    mkdir with parents=True and exist_ok=True, making it safe to call multiple
    times and ensuring robust directory creation even for nested paths.
    """
    Path(index_path).parent.mkdir(parents=True, exist_ok=True)


# Type aliases for CLI parameters to help pydoclint parse Annotated types correctly
_ChunksParquetArg = Annotated[str, typer.Argument(..., help="Path to Parquet/JSONL with chunks")]
_BackendOption = Annotated[str, typer.Option(help="lucene|pure", show_default=True)]
_IndexDirOption = Annotated[
    str | None,
    typer.Option(
        help="Output index directory",
        show_default="./_indices/bm25",
    ),
]
_DenseVectorsArg = Annotated[str, typer.Argument(..., help="Path to dense vectors JSON (skeleton)")]
_IndexPathOption = Annotated[
    str | None,
    typer.Option(
        help="Output FAISS index path",
        show_default="./_indices/faiss/shard_000.idx",
    ),
]
_FactoryOption = Annotated[str, typer.Option(help="FAISS factory string", show_default=True)]
_MetricOption = Annotated[
    str, typer.Option(help="Similarity metric ('ip' or 'l2')", show_default=True)
]
_EnvelopeDirOption = Annotated[
    Path | None,
    typer.Option(
        "--envelope-dir",
        help="Directory where CLI envelopes are written.",
        dir_okay=True,
        file_okay=False,
    ),
]

_ArtifactDirOption = Annotated[
    Path | None,
    typer.Option(
        "--artifact-dir",
        help="Base directory for CLI-generated artifacts (indexes, vectors).",
        dir_okay=True,
        file_okay=False,
    ),
]


@app.command(name=SUBCOMMAND_INDEX_BM25)
def index_bm25(
    ctx: typer.Context,
    chunks_parquet: _ChunksParquetArg,
    backend: _BackendOption = "lucene",
    index_dir: _IndexDirOption = None,
) -> None:
    """Build a BM25 index from chunk metadata and emit a CLI envelope.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state.
    chunks_parquet : _ChunksParquetArg
        Path to Parquet/JSONL file with chunks. Type alias for
        ``Annotated[str, typer.Argument(...)]`` for CLI argument specification.
    backend : _BackendOption, optional
        Backend to use: 'lucene' or 'pure'. Defaults to 'lucene'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    index_dir : _IndexDirOption, optional
        Output index directory. Defaults to './_indices/bm25'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when index construction fails. The
        generated envelope captures the associated Problem Details payload.
    """
    resolved_index_dir = (
        index_dir if index_dir is not None else str(_resolve_artifact_dir(ctx) / "bm25")
    )
    context, builder = _start_command(
        ctx,
        SUBCOMMAND_INDEX_BM25,
        backend=backend,
        chunks_path=chunks_parquet,
        index_dir=resolved_index_dir,
    )
    builder = builder.add_file(
        path=str(Path(chunks_parquet)), status="success", message="Input dataset"
    )

    config = BM25BuildConfig(
        chunks_path=chunks_parquet,
        backend=backend,
        index_dir=resolved_index_dir,
    )
    _log_cli_event(
        logging.INFO,
        "Building BM25 index",
        context,
        backend=backend,
        index_dir=resolved_index_dir,
        chunks_path=chunks_parquet,
    )
    orchestration_cli_context = _cli_context(ctx)
    artifact_fs = orchestration_cli_context.artifact_fs
    artifact_fs.ensure_dir(Path(resolved_index_dir))
    try:
        _prepare_index_directory(config.index_dir)
        backend_used, doc_count = orchestration_cli_context.bm25_builder(config, LOGGER)
        index_path = _get_bm25_index_path(Path(resolved_index_dir), backend_used)
        builder = builder.add_file(
            path=str(index_path),
            status="success",
            message=f"Indexed {doc_count} documents using backend={backend_used}",
        )
        typer.echo(f"BM25 index built at {resolved_index_dir} using backend={backend_used}")
        _log_cli_event(
            logging.INFO,
            "BM25 index built",
            context,
            backend=backend_used,
            documents=doc_count,
            index_path=str(index_path),
        )
        _finish_success(context, builder)
    except FileNotFoundError as exc:
        detail = f"Chunk dataset not found: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_NOT_FOUND,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except (TypeError, json.JSONDecodeError) as exc:
        detail = f"Error loading documents: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="violation",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_INTERNAL_ERROR,
            exc=exc,
        )
        raise typer.Exit(code=1) from exc


def run_index_faiss(*, config: IndexCliConfig) -> dict[str, object]:
    """Build a FAISS index using ``config`` and return build metadata.

    Parameters
    ----------
    config : IndexCliConfig
        Structured configuration describing dense vector input, output index
        path, FAISS factory string, and metric type.

    Returns
    -------
    dict[str, object]
        Summary metadata including ``vector_count`` and ``dimension``.

    Notes
    -----
    Raises ``typer.Exit`` via the surrounding CLI wrapper when any underlying
    helper fails. The wrapper also renders RFC 9457 Problem Details payloads for
    downstream tooling.

    Examples
    --------
    >>> config = IndexCliConfig(
    ...     dense_vectors="vectors.json",
    ...     index_path="./_indices/faiss/shard_000.idx",
    ...     factory="Flat",
    ...     metric="ip",
    ... )
    >>> run_index_faiss(config=config)
    {'vector_count': 0, 'dimension': 0}
    """
    _prepare_index_directory(config.index_path)
    batch = load_vector_batch_from_json(config.dense_vectors)
    matrix_rows = cast("list[list[float]]", batch.matrix.tolist())
    vectors_payload: list[list[float]] = [
        [float(component) for component in row] for row in matrix_rows
    ]
    index_data: dict[str, object] = {
        "keys": [str(vector_id) for vector_id in batch.ids],
        "vectors": vectors_payload,
        "factory": config.factory,
        "metric": config.metric,
    }
    with Path(config.index_path).open("wb") as handle:
        safe_pickle.dump(index_data, handle)
    return {"vector_count": batch.count, "dimension": batch.dimension}


@app.command(name=SUBCOMMAND_INDEX_FAISS)
def index_faiss(
    ctx: typer.Context,
    dense_vectors: _DenseVectorsArg,
    index_path: _IndexPathOption = None,
    factory: _FactoryOption = "Flat",
    metric: _MetricOption = "ip",
) -> None:
    """Build a FAISS index and emit a structured CLI envelope.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state.
    dense_vectors : _DenseVectorsArg
        Path to the dense vector payload (JSON skeleton format). Type alias for
        ``Annotated[str, typer.Argument(...)]`` for CLI argument specification.
    index_path : _IndexPathOption, optional
        Destination path for the serialized FAISS index.
        Defaults to './_indices/faiss/shard_000.idx'.
        Type alias for ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    factory : _FactoryOption, optional
        FAISS factory string describing index topology. Defaults to 'Flat'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    metric : _MetricOption, optional
        Similarity metric identifier (``"ip"`` or ``"l2"``). Defaults to 'ip'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when the command fails. The envelope
        captures the associated Problem Details payload for downstream tooling.

    Examples
    --------
    >>> orchestration_cli = __import__("orchestration.cli").cli
    >>> orchestration_cli.index_faiss(  # doctest: +SKIP
    ...     "vectors.json",
    ...     "./_indices/faiss/shard_000.idx",
    ...     factory="Flat",
    ...     metric="ip",
    ... )
    """
    resolved_index_path = (
        index_path
        if index_path is not None
        else str(_resolve_artifact_dir(ctx) / "faiss" / "shard_000.idx")
    )
    context, builder = _start_command(
        ctx,
        SUBCOMMAND_INDEX_FAISS,
        factory=factory,
        metric=metric,
        dense_vectors=dense_vectors,
        index_path=resolved_index_path,
    )
    builder = builder.add_file(
        path=str(Path(dense_vectors)), status="success", message="Dense vectors source"
    )

    config = IndexCliConfig(
        dense_vectors=dense_vectors,
        index_path=resolved_index_path,
        factory=factory,
        metric=metric,
    )
    _log_cli_event(
        logging.INFO,
        "Building FAISS index",
        context,
        factory=factory,
        metric=metric,
        index_path=resolved_index_path,
        dense_vectors=dense_vectors,
    )
    orchestration_cli_context = _cli_context(ctx)
    artifact_fs = orchestration_cli_context.artifact_fs
    artifact_fs.ensure_dir(Path(resolved_index_path).parent)
    try:
        metadata = orchestration_cli_context.faiss_runner(config)
        builder = builder.add_file(
            path=str(Path(resolved_index_path)),
            status="success",
            message=(
                f"Stored {metadata['vector_count']} vectors (dimension={metadata['dimension']})"
            ),
        )
        builder = builder.add_file(
            path="<configuration>",
            status="success",
            message=json.dumps({"factory": factory, "metric": metric}, sort_keys=True),
        )
        typer.echo(f"FAISS index vectors stored at {resolved_index_path}")
        _log_cli_event(
            logging.INFO,
            "Building FAISS index",
            context,
            vectors=metadata.get("vector_count"),
            dimension=metadata.get("dimension"),
            index_path=index_path,
            factory=factory,
            metric=metric,
        )
        _finish_success(context, builder)
    except VectorValidationError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="violation",
            extras={
                "vector_path": dense_vectors,
                "schema_id": _VECTOR_SCHEMA_ID,
                "validation_errors": list(exc.errors) if hasattr(exc, "errors") else [],
                "errors": list(exc.errors) if hasattr(exc, "errors") else [],
            },
            overrides={"type": _VECTOR_PROBLEM_TYPE},
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except ConfigurationError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=2) from exc
    except (TypeError, json.JSONDecodeError, FileNotFoundError) as exc:
        detail = f"Error loading vectors: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_BAD_REQUEST,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError, RuntimeError, IndexBuildError) as exc:
        detail = f"Error saving index: {exc}"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR, exc=exc)
        raise typer.Exit(code=1) from exc


app.command(name="index_bm25")(index_bm25)
app.command(name="index_faiss")(index_faiss)


@app.command(name=SUBCOMMAND_API)
def api(
    ctx: typer.Context,
    port: int = typer.Option(8080, help="Port to bind", show_default=True),
) -> None:
    """Launch the FastAPI search service using uvicorn.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state.
    port : int
        Port to bind the server to. Defaults to 8080.

    Raises
    ------
    typer.Exit
        Raised when the server cannot be started (missing uvicorn entrypoint or
        missing dependency). Envelopes record the failure metadata for
        downstream tooling.
    """
    context, builder = _start_command(ctx, SUBCOMMAND_API, port=port)
    builder = builder.add_file(path="<api>", status="success", message=f"Configured port {port}")

    try:
        uvicorn_module = importlib.import_module("uvicorn")
    except ImportError as exc:
        detail = "uvicorn is required to run the API server"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR, exc=exc)
        raise typer.Exit(code=1) from exc

    run_attr = getattr(uvicorn_module, "run", None)
    if not callable(run_attr):
        detail = "uvicorn.run entry point not available"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR)
        raise typer.Exit(code=1)

    typer.echo(f"Starting FastAPI service on port {port}")
    run_server = cast("_UvicornRun", run_attr)
    try:
        run_server("search_api.app:app", host="127.0.0.1", port=port, reload=False)
    except KeyboardInterrupt as exc:  # pragma: no cover - manual interruption
        detail = "API server interrupted by user"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_CLIENT_CLOSED,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=130) from exc
    else:
        _finish_success(context, builder)


def _run_e2e_flow() -> list[str]:
    """Execute the end-to-end (e2e) pipeline flow and return flow run IDs.

    This function executes the Prefect-based end-to-end pipeline flow, which
    orchestrates the complete indexing and search pipeline. The function checks
    that Prefect is available before execution, raising a helpful error message
    if the optional dependency is missing.

    Returns
    -------
    list[str]
        List of Prefect flow run IDs generated by the e2e pipeline execution.
        Each run ID corresponds to a workflow execution that can be tracked
        and monitored via Prefect's UI or API.

    Raises
    ------
    RuntimeError
        Raised when Prefect is not available (e2e_flow is None). The error
        message provides installation instructions for adding Prefect support.

    Notes
    -----
    End-to-end flow execution enables comprehensive pipeline testing and
    production deployment. The function delegates to the imported e2e_flow
    function, which is conditionally imported based on Prefect availability.
    Flow run IDs enable tracking and monitoring of pipeline executions through
    Prefect's orchestration platform.
    """
    if _e2e_flow is None:
        msg = (
            "Prefect is required for the e2e pipeline command. "
            "Install it via `pip install -e '.[gpu]'` or add `prefect` manually."
        )
        raise RuntimeError(msg)
    return _e2e_flow()


@app.command(name=SUBCOMMAND_E2E)
def e2e(ctx: typer.Context) -> None:
    """Execute the Prefect-powered end-to-end orchestration pipeline.

    Extended Summary
    ----------------
    This command orchestrates the complete knowledge graph construction pipeline
    using Prefect workflows, enabling comprehensive testing and production
    deployment. It integrates with the shared CLI envelope system to emit
    structured metadata for downstream tooling and monitoring. The function
    delegates to the conditionally imported e2e_flow function, which executes
    all pipeline stages sequentially and reports progress through stage names.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state, configuration, and
        command-line arguments. Used to initialize the CLI envelope builder
        and correlation context for observability.


    Raises
    ------
    typer.Exit
        Raised with exit code 1 when the pipeline cannot be executed (for
        example, Prefect is not installed or a RuntimeError occurs during
        flow execution). The CLI envelope captures the associated Problem
        Details payload for downstream tooling.

    Notes
    -----
    • Side effects: Writes CLI envelopes to stdout via render_cli_envelope,
      emits stage progress messages via typer.echo, and may raise typer.Exit
      to terminate the process with a non-zero exit code.
    • Dependencies: Requires Prefect to be installed (via `pip install -e '.[gpu]'`
      or manual installation). The e2e_flow function is conditionally imported
      and will be None if Prefect is unavailable.
    • Error handling: RuntimeError exceptions from _run_e2e_flow are caught,
      converted to Problem Details format, and emitted via CLI envelope before
      raising typer.Exit(code=1).
    • Observability: Each execution generates a correlation context via
      _start_command and records stage progress in the CLI envelope builder.

    Examples
    --------
    >>> # This function is a Typer CLI command and cannot be called directly
    >>> # It is invoked via: orchestration e2e
    >>> # Successful execution emits stage names and a success envelope
    >>> # Failed execution emits an error envelope and exits with code 1
    """
    context, builder = _start_command(ctx, SUBCOMMAND_E2E)
    try:
        stages = _run_e2e_flow()
    except RuntimeError as exc:
        _handle_failure(
            context,
            detail=str(exc),
            status=STATUS_INTERNAL_ERROR,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc

    for index, stage in enumerate(stages):
        builder = builder.add_file(path=f"<stage:{index}>", status="success", message=stage)
        typer.echo(stage)

    _finish_success(context, builder)


__all__ = ["api", "app", "e2e", "index_bm25", "index_faiss", "run_index_faiss"]


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    app()
LOGGER = logging.getLogger(__name__)
