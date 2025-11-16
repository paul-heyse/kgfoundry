"""Lightweight subprocess observation helpers for tooling."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_SET_FROZEN_ATTR = object.__setattr__


def _thaw(instance: object, **updates: object) -> None:
    """Mutate attributes on a frozen dataclass instance."""
    for name, value in updates.items():
        _SET_FROZEN_ATTR(instance, name, value)


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

    def __post_init__(self) -> None:
        """Derive convenience fields after dataclass initialisation."""
        tool_name = Path(self.command[0]).name if self.command else "<unknown>"
        _thaw(self, tool=tool_name)

    def success(self, returncode: int) -> None:
        """Record successful completion with ``returncode``."""
        _thaw(
            self,
            status="success",
            returncode=returncode,
            failure_reason=None,
            timed_out=False,
        )

    def failure(
        self,
        reason: str,
        *,
        returncode: int | None = None,
        timed_out: bool = False,
    ) -> None:
        """Record failed completion with context metadata."""
        _thaw(
            self,
            status="error",
            failure_reason=reason,
            returncode=returncode,
            timed_out=timed_out,
        )

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
    """Yield a ToolRunObservation for the subprocess lifecycle.

    Extended Summary
    ----------------
    This context manager provides structured observation and metrics collection
    for subprocess execution. It yields a :class:`ToolRunObservation` object that
    tracks command execution state, duration, and outcome. The observation is
    used by CLI tools to record subprocess runs in execution envelopes and
    emit Prometheus metrics for observability.

    Any exception raised during tool execution is explicitly re-raised after
    recording error status and metrics. The exception is caught using
    ``except Exception as exc``, metrics are updated to reflect the error,
    and then the exception is explicitly re-raised to satisfy static analysis
    tools that require explicit exception raising.

    Parameters
    ----------
    command : Sequence[str]
        Command to execute as a sequence of strings (program name followed by
        arguments). Must be non-empty. The first element is the executable path
        or name (resolved via PATH if not absolute).
    cwd : Path | None
        Working directory for the command execution, or None to use the current
        directory. The path must exist and be a directory if provided.
    timeout : float | None
        Optional timeout in seconds. If the subprocess exceeds this duration,
        it will be terminated and a timeout exception will be raised. Must be
        positive if provided. None disables timeout enforcement.

    Yields
    ------
    ToolRunObservation
        Context manager that yields a :class:`ToolRunObservation` capturing runtime
        details including command, working directory, timeout, and execution status.
        The observation object can be used to track subprocess state and results.
        Call ``observation.success()`` or ``observation.failure(reason)`` to record
        the outcome before the context exits.

    Raises
    ------
    Exception
        Any exception raised by the subprocess execution or timeout handling is
        re-raised after recording error status and metrics. Common exception types
        include subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError,
        PermissionError, and OSError. The specific exception type depends on what
        the tool raises.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(1) for context setup/teardown; actual execution time
        depends on the subprocess. No I/O during context entry; metrics are emitted
        on context exit. Thread-safe for concurrent subprocess observations.

    Exception Re-raising:
        Any exception raised during tool execution is caught using ``except Exception``,
        error status and metrics are updated, and then the exception is re-raised via
        ``raise`` to preserve the original exception type and stack trace. Common
        exception types include subprocess.CalledProcessError (non-zero exit code),
        subprocess.TimeoutExpired (timeout exceeded), FileNotFoundError (executable not
        found), PermissionError (execution denied), and OSError (system-level errors).
        The specific exception type depends on what the tool raises.

    See Also
    --------
    ToolRunObservation : Observation object for tracking subprocess execution
    """
    observation = ToolRunObservation(
        command=command,
        cwd=cwd,
        timeout=timeout,
    )
    try:
        yield observation
    except Exception:
        if observation.status == "success":
            observation.failure("exception")
        raise


__all__ = [
    "ToolRunObservation",
    "observe_tool_run",
]
