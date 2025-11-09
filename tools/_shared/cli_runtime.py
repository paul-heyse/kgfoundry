"""Runtime primitives backing the shared CLI façade."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, TypedDict, Unpack

from tools._shared.observability import MetricEmitterError, emitter
from tools._shared.paths import Paths
from tools._shared.problems import ProblemDetails, problem_from_exc

try:  # pragma: no cover - optional dependency
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

MAX_ROUTE_DEPTH: Final[int] = 6
MAX_TOKEN_LENGTH: Final[int] = 48
CHUNK_SIZE: Final[int] = 256 * 1024
CLI_ENVELOPE_VERSION: Final[str] = "1.1.0"

_TOKEN_RE = re.compile(r"[^a-z0-9_-]+")


class CliRunStatus(StrEnum):
    """Enumerated status values for CLI envelopes and logs."""

    SUCCESS = "success"
    ERROR = "error"


def normalize_token(value: str) -> str:
    """Return a normalised command token suitable for envelope metadata.

    Parameters
    ----------
    value : str
        Raw command segment obtained from Click/Typer.

    Returns
    -------
    str
        Sanitised token safe for use in filesystem paths and envelope metadata.

    Raises
    ------
    ValueError
        Raised when ``value`` is empty or resolves to a traversal segment.
    """
    token = _TOKEN_RE.sub("", value.strip().lower().replace(" ", "-").replace(".", "-"))
    if not token or token in {".", ".."}:
        msg = "Command tokens must not be empty or represent traversal."
        raise ValueError(msg)
    return token[:MAX_TOKEN_LENGTH]


def normalize_route(segments: Sequence[str]) -> list[str]:
    """Return the normalised command route derived from ``segments``.

    Parameters
    ----------
    segments : Sequence[str]
        Raw command segments provided by the CLI framework.

    Returns
    -------
    list[str]
        Normalised command route with validated depth and token constraints.

    Raises
    ------
    ValueError
        Raised when the route is empty or exceeds :data:`MAX_ROUTE_DEPTH`.
    """
    route = [normalize_token(segment) for segment in segments]
    if not route:
        msg = "command_path must contain at least one segment."
        raise ValueError(msg)
    if len(route) > MAX_ROUTE_DEPTH:
        msg = f"command_path too deep (max {MAX_ROUTE_DEPTH} segments)."
        raise ValueError(msg)
    return route


def sha256_file(path: Path) -> str:
    """Return the SHA256 digest for ``path``.

    Parameters
    ----------
    path : Path
        Filesystem path to the target artifact.

    Returns
    -------
    str
        Hexadecimal SHA256 digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _CliRunConfigParams(TypedDict, total=False):
    envelope_dir: Path | None
    correlation_id: str | None
    write_envelope_on: Literal["always", "error", "success"]
    stdout_format: Literal["none", "minimal", "full"]
    exit_on_error: bool
    error_code_map: Mapping[type[BaseException], str] | None
    extra_context: Mapping[str, object] | None
    args_summary: Sequence[str] | None
    env_summary: Mapping[str, str] | None


@dataclass(frozen=True, slots=True)
class CliRunConfig:
    """Immutable configuration describing a CLI façade invocation."""

    command_path: Sequence[str]
    envelope_dir: Path | None = None
    correlation_id: str | None = None
    write_envelope_on: Literal["always", "error", "success"] = "always"
    stdout_format: Literal["none", "minimal", "full"] = "minimal"
    exit_on_error: bool = True
    error_code_map: Mapping[type[BaseException], str] | None = None
    extra_context: Mapping[str, object] | None = None
    args_summary: Sequence[str] | None = None
    env_summary: Mapping[str, str] | None = None

    @classmethod
    def from_route(cls, *segments: str, **kwargs: Unpack[_CliRunConfigParams]) -> CliRunConfig:
        """Return a configuration with ``command_path`` normalised from ``segments``.

        Parameters
        ----------
        *segments : str
            Command segments defining the CLI route.
        **kwargs : Unpack[_CliRunConfigParams]
            Additional keyword arguments forwarded to :class:`CliRunConfig`.

        Returns
        -------
        CliRunConfig
            Configuration instance with the normalised command path.
        """
        return cls(command_path=normalize_route(segments), **kwargs)


@dataclass(slots=True, frozen=True)
class CliContext:
    """Runtime metadata supplied to Typer commands executed via :func:`cli_run`."""

    command_path: list[str]
    operation: str
    run_id: str
    correlation_id: str
    started_monotonic: float
    logger: logging.LoggerAdapter
    paths: Paths


@dataclass(frozen=True, slots=True)
class _RunSummary:
    """Compact representation of a CLI execution outcome."""

    operation: str
    run_id: str
    correlation_id: str
    duration_s: float | None
    problem: ProblemDetails | None


@dataclass(slots=True, frozen=True)
class _ExecutionMetadata:
    """Collected metadata derived from the CLI run configuration."""

    route: list[str]
    operation: str
    correlation_id: str
    run_id: str
    paths: Paths
    logger: logging.LoggerAdapter


class EnvelopeBuilder:
    """Utility for constructing CLI envelope payloads."""

    def __init__(
        self,
        *,
        command_path: list[str],
        operation: str,
        run_id: str,
        correlation_id: str,
    ) -> None:
        started_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        command = command_path[0] if command_path else None
        subcommand = command_path[1] if len(command_path) > 1 else None
        self._envelope: dict[str, object] = {
            "version": CLI_ENVELOPE_VERSION,
            "command_path": command_path,
            "operation": operation,
            "command": command,
            "subcommand": subcommand,
            "run_id": run_id,
            "correlation_id": correlation_id,
            "started_at": started_at,
            "status": CliRunStatus.SUCCESS.value,
            "args": [],
            "env": {},
            "artifacts": [],
        }

    def set_args(self, argv: Sequence[str]) -> None:
        """Record the CLI arguments associated with the run.

        Parameters
        ----------
        argv : Sequence[str]
            Iterable of CLI arguments passed to the command.

        """
        self._envelope["args"] = [str(value) for value in argv]

    def set_env(self, env: Mapping[str, str]) -> None:
        """Record redacted environment variables for diagnostics.

        Parameters
        ----------
        env : Mapping[str, str]
            Mapping of environment variables selected for inclusion.

        """
        self._envelope["env"] = dict(env)

    def add_artifact(self, *, kind: str, path: Path, digest: str | None = None) -> None:
        """Append an artifact entry to the envelope.

        Parameters
        ----------
        kind : str
            Logical artifact type (for example ``"file"`` or ``"log"``).
        path : Path
            Filesystem path to the artifact.
        digest : str | None, optional
            Optional SHA256 digest associated with ``path``.

        Raises
        ------
        TypeError
            Raised when the underlying envelope stores artifacts in an
            unexpected structure.
        """
        artifact: dict[str, object] = {"kind": kind, "path": str(path)}
        if digest is not None:
            artifact["sha256"] = digest
        artifacts = self._envelope.get("artifacts")
        if not isinstance(artifacts, list):
            msg = "Envelope artifacts collection must be a list."
            raise TypeError(msg)
        artifacts.append(artifact)

    def set_result(self, *, summary: str, payload: object | None = None) -> None:
        """Record the CLI result summary and optional payload.

        Parameters
        ----------
        summary : str
            Human-readable summary describing the CLI result.
        payload : object | None, optional
            Optional structured payload providing additional metadata.

        """
        result: dict[str, object] = {"summary": summary}
        if payload is not None:
            result["payload"] = payload
        self._envelope["result"] = result

    def set_problem(self, problem: ProblemDetails) -> None:
        """Record a Problem Details payload describing the failure.

        Parameters
        ----------
        problem : ProblemDetails
            Problem description generated from the captured exception.

        """
        self._envelope["status"] = CliRunStatus.ERROR.value
        problem_dict = {key: value for key, value in asdict(problem).items() if value is not None}
        self._envelope["problem"] = problem_dict

    def finalize(self, *, finished_at: datetime | None = None) -> dict[str, object]:
        """Return the fully constructed envelope.

        Parameters
        ----------
        finished_at : datetime | None, optional
            Explicit completion timestamp. Defaults to ``datetime.now(UTC)``.

        Returns
        -------
        dict[str, object]
            Fully populated envelope dictionary ready for persistence.
        """
        completed_at = finished_at or datetime.now(UTC)
        self._envelope["finished_at"] = completed_at.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        return self._envelope


def _now_id() -> str:
    return uuid.uuid4().hex[:6]


def _prepare_logger(
    *,
    operation: str,
    route: list[str],
    run_id: str,
    correlation_id: str,
    extra_context: Mapping[str, object] | None,
) -> logging.LoggerAdapter:
    """Return a logger adapter enriched with CLI metadata.

    Parameters
    ----------
    operation : str
        Operation name for logging context.
    route : list[str]
        Command route segments for logging context.
    run_id : str
        Unique run identifier for logging context.
    correlation_id : str
        Correlation identifier for distributed tracing.
    extra_context : Mapping[str, object] | None
        Optional additional context fields to include in log records.

    Returns
    -------
    logging.LoggerAdapter
        Logger adapter providing structured CLI context fields.
    """
    logger = logging.getLogger("kgf.cli")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    fields: dict[str, object] = {
        "operation": operation,
        "route": route,
        "run_id": run_id,
        "correlation_id": correlation_id,
    }
    if extra_context:
        fields.update(extra_context)
    return logging.LoggerAdapter(logger, extra=fields)


def _prepare_execution_metadata(cfg: CliRunConfig) -> _ExecutionMetadata:
    """Return the execution metadata derived from ``cfg``.

    Parameters
    ----------
    cfg : CliRunConfig
        CLI configuration describing the requested run.

    Returns
    -------
    _ExecutionMetadata
        Immutable metadata bundle used throughout the execution.
    """
    route = normalize_route(cfg.command_path)
    correlation_id = cfg.correlation_id or _now_id()
    run_id = _now_id()
    operation = ".".join(route)
    paths = Paths.discover()
    logger = _prepare_logger(
        operation=operation,
        route=route,
        run_id=run_id,
        correlation_id=correlation_id,
        extra_context=cfg.extra_context,
    )
    return _ExecutionMetadata(
        route=route,
        operation=operation,
        correlation_id=correlation_id,
        run_id=run_id,
        paths=paths,
        logger=logger,
    )


def _build_envelope(
    cfg: CliRunConfig,
    *,
    route: list[str],
    operation: str,
    run_id: str,
    correlation_id: str,
) -> EnvelopeBuilder:
    """Return an envelope builder pre-populated with baseline metadata.

    Parameters
    ----------
    cfg : CliRunConfig
        Configuration containing envelope metadata preferences.
    route : list[str]
        Command route segments for envelope metadata.
    operation : str
        Operation name for envelope metadata.
    run_id : str
        Unique run identifier for envelope metadata.
    correlation_id : str
        Correlation identifier for distributed tracing.

    Returns
    -------
    EnvelopeBuilder
        Envelope builder initialised with route and identity metadata.
    """
    envelope = EnvelopeBuilder(
        command_path=route,
        operation=operation,
        run_id=run_id,
        correlation_id=correlation_id,
    )
    if cfg.args_summary:
        envelope.set_args(cfg.args_summary)
    if cfg.env_summary:
        envelope.set_env(cfg.env_summary)
    return envelope


def _envelope_path(base_dir: Path, *, started_at: str, run_id: str) -> Path:
    """Return the filesystem path for the envelope produced by the CLI run.

    Parameters
    ----------
    base_dir : Path
        Base directory for envelope storage.
    started_at : str
        ISO 8601 timestamp string when the CLI run started.
    run_id : str
        Unique run identifier used in the filename.

    Returns
    -------
    Path
        Target path for the JSON envelope file.
    """
    date_component = started_at[:10].replace("-", "")
    time_component = started_at[11:19].replace(":", "")
    filename = f"{date_component}-{time_component}-{run_id}.json"
    return base_dir / filename


def _should_write_envelope(cfg: CliRunConfig, status: CliRunStatus) -> bool:
    """Return ``True`` when the envelope should be persisted for ``status``.

    Parameters
    ----------
    cfg : CliRunConfig
        Configuration containing envelope persistence preferences.
    status : CliRunStatus
        Current CLI run status (SUCCESS or ERROR).

    Returns
    -------
    bool
        ``True`` when the envelope should be written to disk.
    """
    return (
        cfg.write_envelope_on == "always"
        or (cfg.write_envelope_on == "error" and status is CliRunStatus.ERROR)
        or (cfg.write_envelope_on == "success" and status is CliRunStatus.SUCCESS)
    )


def _validate_envelope(
    paths: Paths, payload: dict[str, object], logger: logging.LoggerAdapter
) -> None:
    """Validate the envelope payload against the optional JSON Schema."""
    if jsonschema is None:
        return
    schema_path = paths.repo_root / "schema" / "tools" / "cli_envelope.json"
    if not schema_path.exists():
        return
    try:
        schema = json.loads(schema_path.read_text())
        jsonschema.validate(payload, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError, OSError) as exc:
        logger.warning("cli_envelope_validation_failed", extra={"error": str(exc)})


def _emit_stdout_message(
    logger: logging.LoggerAdapter,
    *,
    status: CliRunStatus,
    fmt: Literal["none", "minimal", "full"],
    summary: _RunSummary,
) -> None:
    """Emit a human-friendly summary of the CLI run to the structured logger."""
    if fmt == "none":
        return
    if status is CliRunStatus.SUCCESS:
        duration_label = f"{summary.duration_s:.2f}s" if summary.duration_s is not None else "n/a"
        logger.info(
            "cli_run_success",
            extra={
                "stdout_message": (
                    f"{summary.operation} [run={summary.run_id}] ✅ "
                    f"in {duration_label} (corr={summary.correlation_id})"
                )
            },
        )
        return
    problem = summary.problem
    if problem is None:
        return
    code = f"{problem.code}: " if problem.code else ""
    logger.error(
        "cli_run_error",
        extra={
            "stdout_message": (
                f"{summary.operation} [run={summary.run_id}] ❌ {code}{problem.title}"
            ),
            "problem_title": problem.title,
        },
    )


def _emit_metrics(operation: str, status: CliRunStatus, duration_s: float) -> None:
    """Emit an observation describing the CLI execution."""
    with suppress(MetricEmitterError):
        emitter.emit_cli_run(operation=operation, status=status.value, duration_s=duration_s)


def _finalize_envelope(
    envelope: EnvelopeBuilder,
    *,
    status: CliRunStatus,
    started: float,
) -> dict[str, object]:
    """Return the finalised envelope payload with duration metadata.

    Parameters
    ----------
    envelope : EnvelopeBuilder
        Envelope builder to finalize.
    status : CliRunStatus
        Final CLI run status (SUCCESS or ERROR).
    started : float
        Monotonic timestamp when the CLI run started.

    Returns
    -------
    dict[str, object]
        Envelope payload ready for persistence.
    """
    finished_at = datetime.now(UTC)
    payload = envelope.finalize(finished_at=finished_at)
    payload["duration_ms"] = int((time.monotonic() - started) * 1000)
    payload["status"] = status.value
    return payload


@contextmanager
def cli_run(cfg: CliRunConfig) -> Iterator[tuple[CliContext, EnvelopeBuilder]]:
    """Execute a CLI command inside the standardised façade.

    This context manager provides a standardized execution environment for CLI
    commands, handling logging, metrics, envelope generation, and error handling.
    It yields a context object and envelope builder, then finalizes execution
    metadata and optionally writes an envelope file.

    Parameters
    ----------
    cfg : CliRunConfig
        Immutable configuration describing the intended CLI execution, including
        route, operation name, error handling behavior, and output formatting.

    Yields
    ------
    (CliContext, EnvelopeBuilder)
        Tuple containing the live :class:`CliContext` (providing runtime information
        and logger) and the mutable :class:`EnvelopeBuilder` (for accumulating
        execution results and metadata).

    Raises
    ------
    SystemExit
        Raised with exit code ``1`` when an exception occurs inside the context
        and ``cfg.exit_on_error`` evaluates to ``True``. The original exception
        is chained via ``raise SystemExit(1) from error`` where ``error`` is the
        caught exception.
    RuntimeError
        Raised if error is not an Exception subclass (should never happen).

    Notes
    -----
    Exception Propagation:
        When ``cfg.exit_on_error`` is ``False``, any exception raised inside
        the context propagates unchanged to the caller. The function catches
        exceptions using ``except Exception as exc``, stores the exception in
        ``error`` for logging and envelope generation, then re-raises it using
        ``raise exc``. The actual exception type matches whatever was
        originally raised (any subclass of ``Exception``). This is a re-raise
        of the caught exception, preserving its original type and traceback.

        Pydoclint limitation: it doesn't recognize that ``raise exc`` raises
        Exception when ``exc`` is a variable, even though type narrowing
        guarantees it's an Exception subclass. Therefore, Exception is documented
        here in Notes rather than in the Raises section.
    """
    metadata = _prepare_execution_metadata(cfg)
    envelope = _build_envelope(
        cfg,
        route=metadata.route,
        operation=metadata.operation,
        run_id=metadata.run_id,
        correlation_id=metadata.correlation_id,
    )
    started = time.monotonic()
    metadata.logger.info("cli_run_start")

    status = CliRunStatus.SUCCESS
    problem: ProblemDetails | None = None
    error: Exception | None = None
    try:
        context = CliContext(
            command_path=metadata.route,
            operation=metadata.operation,
            run_id=metadata.run_id,
            correlation_id=metadata.correlation_id,
            started_monotonic=started,
            logger=metadata.logger,
            paths=metadata.paths,
        )
        yield context, envelope
    except Exception as exc:  # noqa: BLE001 - intentional: propagate after finalisation
        error = exc
        status = CliRunStatus.ERROR
        problem = problem_from_exc(
            exc,
            code_map=cfg.error_code_map,
            operation=metadata.operation,
            run_id=metadata.run_id,
        )
        envelope.set_problem(problem)
    else:
        status = CliRunStatus.SUCCESS
    finally:
        finished = time.monotonic()
        payload = _finalize_envelope(envelope, status=status, started=started)
        _validate_envelope(metadata.paths, payload, metadata.logger)

        destination_dir = cfg.envelope_dir or metadata.paths.cli_envelope_dir(metadata.route)
        destination_path = _envelope_path(
            destination_dir,
            started_at=str(payload["started_at"]),
            run_id=metadata.run_id,
        )
        if _should_write_envelope(cfg, status):
            destination_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = destination_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp_path.replace(destination_path)

        duration_s = finished - started
        _emit_metrics(metadata.operation, status, duration_s)
        summary = _RunSummary(
            operation=metadata.operation,
            run_id=metadata.run_id,
            correlation_id=metadata.correlation_id,
            duration_s=duration_s,
            problem=problem,
        )
        _emit_stdout_message(
            metadata.logger,
            status=status,
            fmt=cfg.stdout_format,
            summary=summary,
        )
        metadata.logger.info(
            "cli_run_done",
            extra={"status": status.value, "duration_ms": payload["duration_ms"]},
        )

    if error is None:
        return
    if cfg.exit_on_error:
        raise SystemExit(1) from error
    # Re-raise the caught exception (error is always Exception subclass from except clause)
    # Note: This re-raises the original exception, preserving its type and traceback
    # pydoclint limitation: it sees 'raise error' as a variable, not Exception type
    # The docstring correctly documents that Exception (or any subclass) can be raised
    # DOC503: error is a variable holding Exception, not a literal exception type
    # Type narrowing: error is guaranteed to be Exception subclass from except clause
    if not isinstance(error, Exception):
        msg = "error must be an Exception subclass"
        raise TypeError(msg) from None
    exc: Exception = error
    raise exc


__all__ = [
    "CliContext",
    "CliRunConfig",
    "CliRunStatus",
    "EnvelopeBuilder",
    "cli_run",
    "normalize_route",
    "normalize_token",
    "sha256_file",
]
