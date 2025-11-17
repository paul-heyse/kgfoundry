"""Shared helper ensuring multiprocessing uses spawn semantics."""

from __future__ import annotations

import multiprocessing as _multiprocessing
from contextlib import suppress


def configure_spawn_start_method() -> None:
    """Force the global multiprocessing start method to spawn."""
    with suppress(RuntimeError):
        _multiprocessing.set_start_method("spawn")
