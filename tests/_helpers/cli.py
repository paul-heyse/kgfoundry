"""Utilities for invoking Typer/CLI entry points in tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from click.testing import Result
from typer.main import Typer
from typer.testing import CliRunner

_RUNNER = CliRunner(mix_stderr=False)


def invoke(
    app: Typer,
    args: Iterable[str],
    *,
    env: Mapping[str, str] | None = None,
    catch_exceptions: bool = False,
) -> Result:
    """Invoke ``app`` with ``args`` and return the Typer result.

    Extended Summary
    ----------------
    This helper function provides a convenient way to invoke Typer CLI applications
    in tests. It wraps Typer's CliRunner with a shared instance and provides a
    simple interface for testing CLI commands with various arguments and environment
    variables.

    Parameters
    ----------
    app : Typer
        Typer application instance to invoke.
    args : Iterable[str]
        Command-line arguments to pass to the application. Converted to a list
        before invocation.
    env : Mapping[str, str] | None, optional
        Optional environment variables to set during invocation. None uses the
        current environment (default).
    catch_exceptions : bool, optional
        Whether to catch exceptions during invocation (default: False). When True,
        exceptions are captured in the result object instead of propagating.

    Returns
    -------
    Result
        Typer test result object containing exit code, stdout, stderr, and
        exception information (if catch_exceptions=True).

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(1) for setup; actual execution time depends on the CLI
        command. Uses a shared CliRunner instance for efficiency. Thread-safe for
        concurrent test invocations (Typer runner handles isolation).
    """
    return _RUNNER.invoke(app, list(args), env=env, catch_exceptions=catch_exceptions)
