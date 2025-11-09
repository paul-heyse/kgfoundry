"""Compatibility facade for tooling subprocess helpers.

The heavy lifting now lives in :mod:`tools._shared.process`. This module keeps
the longstanding ``run_tool`` entry-point so existing call sites continue to
function without modification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from tools._shared.process import ProcessRunner, ToolExecutionError, ToolRunResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class _ProcessRunnerState:
    runner: ProcessRunner


_PROCESS_STATE: list[_ProcessRunnerState] = [_ProcessRunnerState(ProcessRunner())]


def get_process_runner() -> ProcessRunner:
    """Return the global process runner instance used by :func:`run_tool`.

    Returns
    -------
    ProcessRunner
        Global process runner instance.
    """
    return _PROCESS_STATE[0].runner


def set_process_runner(runner: ProcessRunner) -> None:
    """Replace the global process runner used by :func:`run_tool`.

    Intended for advanced scenarios (e.g. tests) where dependency injection is required. Callers
    should restore the previous runner when finished.
    """
    _PROCESS_STATE[0] = replace(_PROCESS_STATE[0], runner=runner)


def run_tool(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    check: bool = False,
) -> ToolRunResult:
    """Execute ``command`` using the shared :class:`ProcessRunner` policies.

    Parameters
    ----------
    command : Sequence[str]
        Command to execute.
    cwd : Path | None, optional
        Working directory. Default is None.
    env : Mapping[str, str] | None, optional
        Environment variables. Default is None.
    timeout : float | None, optional
        Timeout in seconds. Default is None.
    check : bool, optional
        Raise on non-zero exit. Default is False.

    Returns
    -------
    ToolRunResult
        Execution result.

    Note
    ----
    This function calls :meth:`ProcessRunner.run` which may raise
    :exc:`ToolExecutionError`. See :class:`ProcessRunner` for details.
    """
    return _PROCESS_STATE[0].runner.run(
        command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=check,
    )


__all__ = [
    "ProcessRunner",
    "ToolExecutionError",
    "ToolRunResult",
    "get_process_runner",
    "run_tool",
    "set_process_runner",
]
