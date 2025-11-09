"""Lifecycle helpers for documentation toolchain entrypoints.

The documentation toolchain contains multiple commands (symbol index builds,
symbol deltas, artifact validation) that historically implemented their own
logging, metrics, and Problem Details handling. This module centralises the
shared mechanics so the command modules can focus on domain-specific logic
while still emitting consistent observability signals.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from tools import (
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    render_problem,
)

from docs._scripts import shared
from kgfoundry_common.logging import LoggerAdapter, get_logger, set_correlation_id
from kgfoundry_common.prometheus import build_counter, build_histogram

if TYPE_CHECKING:
    from kgfoundry_common.prometheus import CounterLike, HistogramLike

ArgvType = Sequence[str] | None
ParserConfigurator = Callable[[argparse.ArgumentParser], None]


@dataclass(slots=True, frozen=True)
class DocToolMetadata:
    """Static descriptors for a documentation toolchain command."""

    operation: str
    description: str
    problem_type: str


@dataclass(slots=True, frozen=True)
class DocToolError(RuntimeError):
    """Structured exception carrying Problem Details metadata.

    Attributes
    ----------
    problem : ProblemDetailsDict
        RFC 9457 Problem Details payload.
    exit_code : int
        Exit code that should be returned by the CLI.
    status_label : str
        Metrics/logging label representing failure status (``"error"``,
        ``"cancelled"``, etc.).

    Parameters
    ----------
    message : str
        Human-readable error message.
    problem : ProblemDetailsDict
        RFC 9457 Problem Details payload.
    exit_code : int
        Exit code that should be returned by the CLI.
    status_label : str
        Metrics/logging label representing failure status (``"error"``,
        ``"cancelled"``, etc.).
    """

    problem: ProblemDetailsDict
    exit_code: int
    status_label: str

    def __init__(
        self,
        message: str,
        *,
        problem: ProblemDetailsDict,
        exit_code: int,
        status_label: str,
    ) -> None:
        super().__init__(message)
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "status_label", status_label)


@dataclass(slots=True, frozen=True)
class ProblemDetailsInput:
    """Inputs required to build a Problem Details payload."""

    title: str
    detail: str
    status: int
    instance: str
    extensions: Mapping[str, JsonValue] | None = None
    problem_type: str | None = None


@dataclass(slots=True, frozen=True)
class DocToolSettings:
    """Common runtime configuration for doc toolchain commands."""

    metadata: DocToolMetadata
    argv: tuple[str, ...]
    environment: shared.BuildEnvironment
    docs_settings: shared.DocsSettings
    docs_build_dir: Path
    correlation_id: str
    raw_args: argparse.Namespace

    @property
    def root(self) -> Path:
        """Return repository root for convenience."""
        return self.environment.root

    @classmethod
    def parse_args(
        cls,
        argv: ArgvType,
        *,
        metadata: DocToolMetadata,
        configure: ParserConfigurator | None = None,
    ) -> DocToolSettings:
        """Parse CLI arguments and return a :class:`DocToolSettings` instance.

        Parameters
        ----------
        argv : ArgvType
            Command-line arguments supplied to the tool (``None`` defaults to ``sys.argv``).
        metadata : DocToolMetadata
            Static descriptors describing the tool (operation name, description, problem type).
        configure : ParserConfigurator | None, optional
            Optional callback that may add additional parser arguments before parsing occurs.

        Returns
        -------
        DocToolSettings
            Fully populated settings object used to construct lifecycle context objects.
        """
        env = shared.detect_environment()
        shared.ensure_sys_paths(env)
        docs_settings = shared.load_settings()

        parser = argparse.ArgumentParser(description=metadata.description)
        parser.add_argument(
            "--docs-build-dir",
            type=Path,
            default=None,
            help=(
                "Override the documentation build directory. Defaults to the "
                "value derived from docs settings."
            ),
        )
        parser.add_argument(
            "--correlation-id",
            default=None,
            help=(
                "Correlation identifier used for structured logging and Problem Details emission."
            ),
        )
        if configure is not None:
            configure(parser)

        namespace = parser.parse_args(list(argv) if argv is not None else None)
        docs_build_override = getattr(namespace, "docs_build_dir", None)
        docs_build_dir = (
            Path(docs_build_override).resolve()
            if docs_build_override is not None
            else docs_settings.docs_build_dir
        )
        if docs_build_override is not None:
            docs_settings = replace(docs_settings, docs_build_dir=docs_build_dir)

        raw_correlation_id = getattr(namespace, "correlation_id", None)
        correlation_id = raw_correlation_id or uuid.uuid4().hex

        argv_tuple = tuple(argv) if argv is not None else tuple(sys.argv[1:])

        return cls(
            metadata=metadata,
            argv=argv_tuple,
            environment=env,
            docs_settings=docs_settings,
            docs_build_dir=docs_build_dir,
            correlation_id=correlation_id,
            raw_args=namespace,
        )

    def get_arg(self, name: str, default: JsonValue | None = None) -> JsonValue | None:
        """Return an attribute from the raw namespace with a default.

        Parameters
        ----------
        name : str
            Attribute name to fetch from the parsed ``argparse`` namespace.
        default : JsonValue | None, optional
            Value returned when ``name`` is missing, defaults to ``None``.

        Returns
        -------
        JsonValue | None
            Parsed argument value or ``default`` when the attribute is absent.
        """
        return getattr(self.raw_args, name, default)


@lru_cache(maxsize=1)
def _docs_operation_counter() -> CounterLike:
    return build_counter(
        "kgfoundry_docs_operation_total",
        "Total documentation toolchain operations grouped by status.",
        ("operation", "status"),
    )


@lru_cache(maxsize=1)
def _docs_operation_duration() -> HistogramLike:
    return build_histogram(
        "kgfoundry_docs_operation_duration_seconds",
        "Duration of documentation toolchain operations in seconds.",
        ("operation", "status"),
    )


@dataclass(slots=True, frozen=True)
class DocMetrics:
    """Prometheus-backed metrics helpers for doc toolchain commands."""

    operation: str
    _counter: CounterLike = field(init=False, repr=False)
    _histogram: HistogramLike = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_counter", _docs_operation_counter())
        object.__setattr__(self, "_histogram", _docs_operation_duration())

    def observe_success(self, duration_seconds: float) -> None:
        """Record a successful run."""
        self._counter.labels(operation=self.operation, status="success").inc()
        self._histogram.labels(operation=self.operation, status="success").observe(duration_seconds)

    def observe_failure(self, status: str, duration_seconds: float) -> None:
        """Record a failed run for ``status`` label."""
        self._counter.labels(operation=self.operation, status=status).inc()
        self._histogram.labels(operation=self.operation, status=status).observe(duration_seconds)


@dataclass(slots=True, frozen=True)
class DocToolContext:
    """Runtime context shared across doc toolchain operations."""

    settings: DocToolSettings
    logger: LoggerAdapter
    metrics: DocMetrics

    def bind(self, *, artifact: str | None = None, **fields: object) -> LoggerAdapter:
        """Return a logger adapter enriched with ``artifact`` and extra fields.

        Parameters
        ----------
        artifact : str | None, optional
            Artifact identifier to include in log records.
        **fields : object
            Additional structured fields injected into subsequent log entries.

        Returns
        -------
        LoggerAdapter
            Logger adapter pre-bound with lifecycle correlation metadata.
        """
        base_adapter = self.logger
        merged_fields: dict[str, object] = {}
        existing_extra = getattr(base_adapter, "extra", None)
        if isinstance(existing_extra, dict):
            merged_fields.update(existing_extra)
        elif hasattr(existing_extra, "to_dict"):
            merged_fields.update(existing_extra.to_dict())  # type: ignore[call-arg]

        merged_fields.update(
            {
                "operation": self.settings.metadata.operation,
                "correlation_id": self.settings.correlation_id,
            }
        )
        if artifact is not None:
            merged_fields["artifact"] = artifact
        if fields:
            merged_fields.update(fields)

        underlying_logger = base_adapter.logger
        return LoggerAdapter(underlying_logger, merged_fields)

    def instance(self, suffix: str) -> str:
        """Return a URN identifying the current operation instance.

        Parameters
        ----------
        suffix : str
            Instance-specific suffix appended to the URN.

        Returns
        -------
        str
            Operation-scoped URN suitable for Problem Details ``instance`` fields.
        """
        return f"urn:docs:{self.settings.metadata.operation}:{suffix}"

    def problem_details(self, payload: ProblemDetailsInput) -> ProblemDetailsDict:
        """Build a Problem Details payload scoped to this operation.

        Parameters
        ----------
        payload : ProblemDetailsInput
            Structured inputs describing the generated Problem Details.

        Returns
        -------
        ProblemDetailsDict
            RFC 9457 Problem Details payload ready for emission.
        """
        return build_problem_details(
            ProblemDetailsParams(
                type=payload.problem_type
                or f"https://kgfoundry.dev/problems/{self.settings.metadata.problem_type}",
                title=payload.title,
                status=payload.status,
                detail=payload.detail,
                instance=payload.instance,
                extensions=payload.extensions,
            )
        )


def create_doc_tool_context(settings: DocToolSettings) -> DocToolContext:
    """Return a :class:`DocToolContext` configured for ``settings``.

    Parameters
    ----------
    settings : DocToolSettings
        Parsed settings describing runtime configuration for the tool.

    Returns
    -------
    DocToolContext
        Lifecycle-aware context supplying logging, metrics, and Problem Details helpers.
    """
    base_logger = get_logger(f"docs.toolchain.{settings.metadata.operation}")
    adapter = LoggerAdapter(
        base_logger.logger,
        {
            "operation": settings.metadata.operation,
            "correlation_id": settings.correlation_id,
        },
    )
    set_correlation_id(settings.correlation_id)
    metrics = DocMetrics(settings.metadata.operation)
    return DocToolContext(settings=settings, logger=adapter, metrics=metrics)


@dataclass(slots=True, frozen=True)
class DocLifecycle:
    """Manage start/stop logging, metrics, and error handling for operations."""

    context: DocToolContext
    problem_stream: TextIO = sys.stderr

    def run(self, work: Callable[[DocToolContext], int]) -> int:
        """Execute ``work`` under structured lifecycle management.

        Parameters
        ----------
        work : Callable[[DocToolContext], int]
            Callable performing the core command logic.

        Returns
        -------
        int
            Exit code reported by ``work`` or synthesized by lifecycle error handlers.
        """
        start = time.monotonic()
        logger = self.context.logger
        logger.info("Operation started", extra={"status": "started"})

        try:
            exit_code = work(self.context)
        except DocToolError as error:
            duration = time.monotonic() - start
            self.context.metrics.observe_failure(error.status_label, duration)
            self._emit_problem(error.problem)
            logger.exception(
                "Operation failed",
                extra={
                    "status": error.status_label,
                    "duration_ms": duration * 1000.0,
                    "exit_code": error.exit_code,
                },
            )
            return error.exit_code
        except KeyboardInterrupt:
            duration = time.monotonic() - start
            self.context.metrics.observe_failure("cancelled", duration)
            problem = self.context.problem_details(
                ProblemDetailsInput(
                    title="Operation cancelled",
                    detail="Documentation toolchain command interrupted by user",
                    status=499,
                    instance=self.context.instance("cancelled"),
                )
            )
            self._emit_problem(problem)
            logger.warning(
                "Operation cancelled",
                extra={"status": "cancelled", "duration_ms": duration * 1000.0},
            )
            return 130
        except Exception as exc:  # pragma: no cover - defensive safeguard
            duration = time.monotonic() - start
            problem = self.context.problem_details(
                ProblemDetailsInput(
                    title="Operation failed",
                    detail=str(exc),
                    status=500,
                    instance=self.context.instance("unexpected-error"),
                    extensions={"exception": type(exc).__name__},
                )
            )
            self._emit_problem(problem)
            logger.exception(
                "Operation raised an unexpected exception",
                extra={"status": "error", "duration_ms": duration * 1000.0},
            )
            self.context.metrics.observe_failure("error", duration)
            return 1

        duration = time.monotonic() - start
        self.context.metrics.observe_success(duration)
        logger.info(
            "Operation completed",
            extra={
                "status": "success",
                "duration_ms": duration * 1000.0,
                "exit_code": exit_code,
            },
        )
        return exit_code

    def _emit_problem(self, problem: ProblemDetailsDict) -> None:
        rendered = render_problem(problem)
        self.problem_stream.write(rendered + "\n")
        self.problem_stream.flush()


__all__ = [
    "DocLifecycle",
    "DocMetrics",
    "DocToolContext",
    "DocToolError",
    "DocToolMetadata",
    "DocToolSettings",
    "ProblemDetailsInput",
    "create_doc_tool_context",
]
