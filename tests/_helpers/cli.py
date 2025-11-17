"""Utilities for invoking Typer/CLI entry points in tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, cast

from click.testing import Result
from typer.main import Typer
from typer.testing import CliRunner

_RUNNER = CliRunner(mix_stderr=False)


class _ArgNormalizer(Protocol):
    def __call__(self, argv: Sequence[str]) -> list[str]: ...


def invoke(
    app: Typer,
    args: Iterable[str],
    *,
    env: Mapping[str, str] | None = None,
    catch_exceptions: bool = False,
    obj: object | None = None,
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
    obj : object | None, optional
        Optional Click ``obj`` passed to the CLI context. Defaults to None.
        Pass dictionaries containing CLI-specific contexts (e.g.,
        ``{"splade_cli_context": ctx}``) and ``cli_run_overrides`` entries such as
        ``{"envelope_dir": tmp_path}`` to redirect envelope output without
        touching module globals.

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
        CLI injection:
            Preferred pattern is to pass dependency contexts and overrides via ``obj``.
            Example::

                context = MyCliContext(...)
                invoke(
                    app,
                    args,
                    obj={
                        "my_cli_context": context,
                        "cli_run_overrides": {"envelope_dir": tmp_path},
                    },
                )
    """
    arg_list = list(args)
    normalizer_obj = getattr(app, "argv_normalizer", None)
    if normalizer_obj is None:
        normalizer_obj = getattr(app, "__kgf_normalize_args__", None)
    if normalizer_obj is not None and callable(normalizer_obj):
        normalizer = cast("_ArgNormalizer", normalizer_obj)
        normalized = normalizer(["cli", *arg_list])
        arg_list = normalized[1:]
    return _RUNNER.invoke(
        app,
        arg_list,
        env=env,
        catch_exceptions=catch_exceptions,
        obj=obj,
    )
