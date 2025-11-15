"""Observability helpers (telemetry + lightweight timelines).

This module intentionally avoids importing submodules eagerly to prevent cycles
with ``codeintel_rev.runtime`` during early application startup. Callers can
access attributes lazily (``codeintel_rev.observability.timeline``) and the
submodule will be loaded on first access.
"""

from __future__ import annotations

import importlib
from types import ModuleType

_SUBMODULES = {
    "execution_ledger",
    "flight_recorder",
    "metrics",
    "otel",
    "runtime_observer",
    "semantic_conventions",
    "timeline",
}

__all__ = sorted(_SUBMODULES)


def __getattr__(name: str) -> ModuleType:
    if name not in _SUBMODULES:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    module = importlib.import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
