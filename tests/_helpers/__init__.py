"""Test helper utilities with lazy submodule loading."""

from __future__ import annotations

import importlib
from types import ModuleType

from tests._helpers.process import run_process

__all__ = ("run_process",)


def __getattr__(name: str) -> ModuleType:
    """Lazily import heavy helper modules on attribute access.

    Parameters
    ----------
    name : str
        Helper module attribute requested from :mod:`tests._helpers`.

    Returns
    -------
    ModuleType
        Imported helper module corresponding to ``name``.

    Raises
    ------
    AttributeError
        If ``name`` is not a supported helper module.
    """
    if name in {"adapters", "assertions", "cli", "constants", "http", "ml", "repo", "settings"}:
        return importlib.import_module(f"tests._helpers.{name}")
    message = f"Module {name!r} is not part of tests._helpers"
    raise AttributeError(message)
