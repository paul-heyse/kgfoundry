"""Observability helpers for tooling subprocess execution.

This module defines Prometheus metrics and OpenTelemetry span helpers that are
consumed by :mod:`tools._shared.proc`. The helpers degrade gracefully when the
optional Prometheus or OpenTelemetry dependencies are not installed so the
calling code never needs to guard imports. Metrics are registered once at import
time using well-known names to make it easy for dashboards to scrape the values
exposed by tooling processes.

For the authoritative contract (typed metric interfaces, structured logging
fields, and fallback semantics) see ``tools/_shared/observability_facade.md``
and the spec scenario documented in
``openspec/changes/pyrefly-suppression-bust/specs/code-quality/spec.md``.
"""

from __future__ import annotations

import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from kgfoundry_common.observability import start_span
from tools._shared.logging import get_logger, with_fields
from tools._shared.prometheus import (
    build_counter,
    build_histogram,
)
from tools._shared.settings import get_runtime_settings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from tools._shared.logging import StructuredLoggerAdapter
    from tools._shared.prometheus import (
        CounterLike,
        HistogramLike,
    )

LOGGER = get_logger(__name__)


TOOL_RUNS_TOTAL: CounterLike = build_counter(
    "tool_runs_total",
    "Total tooling subprocess invocations",
    labelnames=["tool", "status"],
)

TOOL_FAILURES_TOTAL: CounterLike = build_counter(
    "tool_failures_total",
    "Count of tooling subprocess failures grouped by reason",
    labelnames=["tool", "reason"],
)

TOOL_DURATION_SECONDS: HistogramLike = build_histogram(
    "tool_duration_seconds",
    "Tooling subprocess duration in seconds",
    labelnames=["tool", "status"],
)


@dataclass(slots=True, frozen=True)
class ToolRunObservation:
    """Captures runtime details for a single subprocess invocation."""

    command: Sequence[str]
    cwd: Path | None
    timeout: float | None
    tool: str = field(init=False)
    status: str = field(default="success", init=False)
    failure_reason: str | None = field(default=None, init=False)
    returncode: int | None = field(default=None, init=False)
    timed_out: bool = field(default=False, init=False)
    start_time: float = field(default_factory=time.monotonic, init=False)
    metrics_enabled: bool = True
    tracing_enabled: bool = True

    def __post_init__(self) -> None:
        """Derive convenience fields after dataclass initialisation."""
        self.tool = Path(self.command[0]).name if self.command else "<unknown>"

    def success(self, returncode: int) -> None:
        """Record successful completion with ``returncode``."""
        self.status = "success"
        self.returncode = returncode
        self.failure_reason = None
        self.timed_out = False

    def failure(
        self,
        reason: str,
        *,
        returncode: int | None = None,
        timed_out: bool = False,
    ) -> None:
        """Record failed completion with context metadata."""
        self.status = "error"
        self.failure_reason = reason
        self.returncode = returncode
        self.timed_out = timed_out

    def duration_seconds(self) -> float:
        """Return the elapsed duration in seconds.

        Returns
        -------
        float
            Duration in seconds since initialization.
        """
        return time.monotonic() - self.start_time


@contextmanager
def observe_tool_run(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout: float | None,
) -> Iterator[ToolRunObservation]:
    """Record metrics and tracing for a subprocess invocation.

    This context manager wraps subprocess execution with observability features,
    including Prometheus metrics, OpenTelemetry tracing, and structured logging.
    It yields a ToolRunObservation object that tracks the subprocess lifecycle
    and automatically records metrics when the context exits.

    Parameters
    ----------
    command : Sequence[str]
        Command to execute as a sequence of strings (program name followed by arguments).
    cwd : Path | None
        Working directory for the command execution, or None to use the current directory.
    timeout : float | None
        Optional timeout in seconds. If the subprocess exceeds this duration,
        it will be terminated and a timeout exception will be raised.

    Yields
    ------
    ToolRunObservation
        Context manager that yields a :class:`ToolRunObservation` capturing runtime
        details including command, working directory, timeout, and execution status.
        The observation object can be used to track subprocess state and results.

    Raises
    ------
    Exception
        Any exception raised during tool execution is explicitly re-raised after
        recording error status and metrics. The exception is caught using
        ``except Exception as exc``, metrics are updated to reflect the error,
        and then the exception is explicitly re-raised. The specific exception
        type depends on what the tool raises (e.g., subprocess errors, timeout
        errors, etc.).

    Notes
    -----
    Any exception raised during tool execution is explicitly re-raised after
    recording error status and metrics. The exception is caught using
    ``except Exception as exc``, metrics are updated to reflect the error,
    and then the exception is explicitly re-raised using ``raise exc``
    to satisfy static analysis tools that require explicit exception raising.
    The specific exception type depends on what the tool raises (e.g.,
    subprocess errors, timeout errors, etc.).
    """
    settings = get_runtime_settings()
    observation = ToolRunObservation(
        command=command,
        cwd=cwd,
        timeout=timeout,
        metrics_enabled=settings.metrics_enabled,
        tracing_enabled=settings.tracing_enabled,
    )
    command_parts: list[str] = list(command)
    logger = with_fields(
        LOGGER,
        tool=observation.tool,
        command=command_parts,
        cwd=str(cwd) if cwd else None,
        timeout_seconds=timeout,
    )
    span_name = f"tools.run.{observation.tool}"
    span_attributes: dict[str, str | int | float | bool | None]
    span_attributes = {
        "tool": observation.tool,
        "cwd": str(cwd) if cwd else "",
        "timeout_s": timeout if timeout is not None else -1.0,
    }

    span_context = (
        start_span(
            span_name, attributes={k: v for k, v in span_attributes.items() if v is not None}
        )
        if observation.tracing_enabled
        else nullcontext()
    )

    with span_context:
        try:
            yield observation
        except Exception as exc:
            if observation.status == "success":
                observation.failure("exception")
            _record(observation, logger)
            raise exc  # noqa: TRY201
        else:
            _record(observation, logger)


def _record(
    observation: ToolRunObservation,
    logger: StructuredLoggerAdapter,
) -> None:
    """Persist metrics and structured logs for the finished observation."""
    duration = observation.duration_seconds()
    status = observation.status
    if observation.metrics_enabled:
        TOOL_RUNS_TOTAL.labels(tool=observation.tool, status=status).inc()
        TOOL_DURATION_SECONDS.labels(tool=observation.tool, status=status).observe(duration)
    extra: dict[str, object] = {
        "duration_ms": duration * 1000,
        "tool": observation.tool,
        "status": status,
        "returncode": observation.returncode,
        "timed_out": observation.timed_out,
    }
    if status == "error":
        reason = observation.failure_reason or "unknown"
        if observation.metrics_enabled:
            TOOL_FAILURES_TOTAL.labels(tool=observation.tool, reason=reason).inc()
        extra["reason"] = reason
        logger.error("Tool run failed", extra=extra)
    else:
        logger.info("Tool run succeeded", extra=extra)


__all__: Final[list[str]] = [
    "ToolRunObservation",
    "observe_tool_run",
]
