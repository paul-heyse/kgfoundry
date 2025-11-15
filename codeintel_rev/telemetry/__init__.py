"""Phase-0 telemetry helpers (tracing, metrics, logging, run reports)."""

from __future__ import annotations

import importlib
from types import ModuleType

_SUBMODULE_EXPORTS = {
    "context": [
        "attach_context_attrs",
        "current_run_id",
        "current_session",
        "current_stage",
        "request_tool_var",
        "run_id_var",
        "session_id_var",
        "set_request_stage",
        "telemetry_context",
    ],
    "decorators": [
        "trace_span",
        "trace_step",
    ],
    "events": [
        "RunCheckpoint",
        "TimelineEvent",
        "checkpoint_event",
    ],
    "logging": [
        "install_structured_logging",
    ],
}

__all__ = [symbol for symbols in _SUBMODULE_EXPORTS.values() for symbol in symbols]


def __getattr__(name: str) -> object:
    for module_name, exports in _SUBMODULE_EXPORTS.items():
        if name in exports:
            module = importlib.import_module(f"{__name__}.{module_name}")
            value = getattr(module, name)
            globals()[name] = value
            return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
