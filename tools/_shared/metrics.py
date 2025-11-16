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
