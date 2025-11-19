"""Utilities for consistent multiprocessing start methods."""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from multiprocessing.context import SpawnContext
from typing import cast

__all__ = [
    "ensure_spawn_start_method",
    "get_spawn_context",
    "spawn_process",
    "spawn_process_pool",
]


@cache
def get_spawn_context() -> SpawnContext:
    """Return a cached ``spawn`` context for launching new processes.

    Returns
    -------
    SpawnContext
        Context bound to the ``spawn`` start method.
    """
    return mp.get_context("spawn")


def ensure_spawn_start_method(*, force: bool = False) -> None:
    """Set the global start method to ``spawn`` when possible.

    Parameters
    ----------
    force : bool, optional
        When True, forces resetting the start method even if it was configured
        previously. Defaults to False.
    """
    try:
        mp.set_start_method("spawn", force=force)
    except RuntimeError:
        # Start method already initialized; nothing to change.
        return


def spawn_process(
    target: Callable[..., object],
    *,
    args: tuple[object, ...] = (),
    kwargs: dict[str, object] | None = None,
    daemon: bool | None = None,
    name: str | None = None,
) -> mp.Process:
    """Return a ``spawn``-backed :class:`multiprocessing.Process`.

    Parameters
    ----------
    target : Callable[..., object]
        Callable executed inside the child process.
    args : tuple[object, ...], optional
        Positional arguments forwarded to ``target``.
    kwargs : dict[str, object] | None, optional
        Keyword arguments forwarded to ``target``.
    daemon : bool | None, optional
        Optional daemon flag applied to the process.
    name : str | None, optional
        Optional name assigned to the process.

    Returns
    -------
    mp.Process
        Process instance configured with the ``spawn`` start method.
    """
    ctx = get_spawn_context()
    process = cast("mp.Process", ctx.Process(target=target, args=args, kwargs=kwargs or {}))
    if daemon is not None:
        process.daemon = daemon
    if name is not None:
        process.name = name
    return process


def spawn_process_pool(*, max_workers: int | None = None) -> ProcessPoolExecutor:
    """Return a ProcessPoolExecutor bound to the ``spawn`` context.

    Parameters
    ----------
    max_workers : int | None, optional
        Maximum number of worker processes. None means use default.
        Defaults to None.

    Returns
    -------
    ProcessPoolExecutor
        Executor configured to use the ``spawn`` start method.
    """
    return ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=get_spawn_context(),
    )
