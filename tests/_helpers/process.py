"""Subprocess helpers for tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from kgfoundry_common.subprocess_utils import run_subprocess

DEFAULT_TIMEOUT: Final[int | None] = None


def run_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> str:
    """Execute a subprocess command using the hardened helper.

    Parameters
    ----------
    command : Sequence[str]
        Command and arguments to execute.
    cwd : Path | None, optional
        Working directory for the subprocess.
    env : Mapping[str, str] | None, optional
        Environment variables to pass to the subprocess.
    timeout : int | None, optional
        Maximum execution time in seconds. Defaults to the library default.

    Returns
    -------
    str
        Captured stdout from the subprocess invocation.
    """
    return run_subprocess(
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        timeout=timeout,
    )


__all__ = ["run_process"]
