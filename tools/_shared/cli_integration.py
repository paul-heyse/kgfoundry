"""Reusable wrappers for integrating Typer/Click commands with the CLI façade."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeVar

import click

from tools._shared.cli_runtime import CliContext, CliRunConfig, EnvelopeBuilder, cli_run

_SUMMARY_ENV_KEYS: tuple[str, ...] = (
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CUDA_VISIBLE_DEVICES",
)

P = ParamSpec("P")
R = TypeVar("R")


def current_route(*, include_root: bool = False) -> list[str]:
    """Return the active Click/Typer command route.

    Parameters
    ----------
    include_root : bool, optional
        When ``True`` the root binary name is retained as the first segment.

    Returns
    -------
    list[str]
        Normalised command route, excluding the binary name by default.
    """
    ctx: click.Context | None = click.get_current_context()
    route: list[str] = []
    while ctx is not None:
        if ctx.info_name:
            route.append(ctx.info_name)
        ctx = ctx.parent
    route.reverse()
    if not include_root and route:
        route = route[1:] if len(route) > 1 else route
    return route


def cli_operation(
    *,
    echo_args: bool = True,
    echo_env: bool = False,
) -> Callable[[Callable[Concatenate[CliContext, EnvelopeBuilder, P], R]], Callable[P, R]]:
    """Wrap a Typer/Click command so it executes within :func:`cli_run`.

    Parameters
    ----------
    echo_args : bool, optional
        When ``True`` include function keyword arguments in the CLI envelope.
    echo_env : bool, optional
        When ``True`` include a small redacted environment summary.

    Returns
    -------
    Callable[[Callable[Concatenate[CliContext, EnvelopeBuilder, P], R]], Callable[P, R]]
        Decorator that adapts the original callable so it receives the
        ``CliContext`` and ``EnvelopeBuilder`` objects provided by
        :func:`cli_run`.
    """

    def deco(
        fn: Callable[Concatenate[CliContext, EnvelopeBuilder, P], R],
    ) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            route = current_route()
            cfg = CliRunConfig(
                command_path=route,
                args_summary=(
                    [f"{key}={value}" for key, value in kwargs.items()] if echo_args else None
                ),
                env_summary=_collect_env_summary() if echo_env else None,
            )
            with cli_run(cfg) as (ctx, env):
                return fn(ctx, env, *args, **kwargs)

        return wrapper

    return deco


def _collect_env_summary() -> dict[str, str]:
    """Return a redacted subset of environment variables for envelope logging.

    Returns
    -------
    dict[str, str]
        Mapping of environment variable names to their redacted values.
    """
    return {key: os.environ.get(key, "") for key in _SUMMARY_ENV_KEYS}


__all__ = ["cli_operation", "current_route"]
