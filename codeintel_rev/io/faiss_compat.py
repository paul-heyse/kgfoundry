"""Compatibility helpers for importing FAISS safely on Python 3.13+."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from types import ModuleType

from codeintel_rev.typing import gate_import

_SWIG_WARNING_MODULE = r"importlib\._bootstrap"


def load_faiss_module(reason: str) -> ModuleType:
    """Import FAISS and sanitize SWIG-generated types.

    Parameters
    ----------
    reason : str
        Human-readable reason forwarded to :func:`gate_import`.

    Returns
    -------
    ModuleType
        Imported :mod:`faiss` module with type metadata normalized.

    Raises
    ------
    TypeError
        If :func:`gate_import` returns an unexpected object.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            module=_SWIG_WARNING_MODULE,
        )
        module = gate_import("faiss", reason)
    if not isinstance(module, ModuleType):  # pragma: no cover - defensive
        msg = "gate_import('faiss', ...) must return a module"
        raise TypeError(msg)
    return sanitize_faiss_bindings(module)


def sanitize_faiss_bindings(module: ModuleType) -> ModuleType:
    """Ensure SWIG-created types report their defining module.

    Parameters
    ----------
    module : ModuleType
        Root :mod:`faiss` module that was imported.

    Returns
    -------
    ModuleType
        The same module reference, after fixing metadata.
    """
    for name, candidate in _iter_faiss_modules():
        _assign_missing_module_attr(candidate, name)
    return module


def _iter_faiss_modules() -> Iterator[tuple[str, ModuleType]]:
    for name, candidate in list(sys.modules.items()):
        if not name.startswith("faiss"):
            continue
        if isinstance(candidate, ModuleType):
            yield name, candidate


def _assign_missing_module_attr(target: ModuleType, module_name: str) -> None:
    for attr_name in dir(target):
        attr = getattr(target, attr_name, None)
        if isinstance(attr, type):
            if getattr(attr, "__module__", None):
                continue
            try:
                attr.__module__ = module_name
            except (AttributeError, TypeError):  # pragma: no cover - defensive
                continue
