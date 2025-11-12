"""MCP server implementation and tool adapters for CodeIntel."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

__all__ = ["service_context"]

if TYPE_CHECKING:  # pragma: no cover - import-time heavy module avoided
    from codeintel_rev.mcp_server import service_context

_EXPORTS: dict[str, str] = {"service_context": "codeintel_rev.mcp_server.service_context"}


def __getattr__(name: str) -> ModuleType:
    """Lazy-load heavy submodules to avoid circular imports.

    Parameters
    ----------
    name : str
        Attribute name to resolve.

    Returns
    -------
    ModuleType
        Imported module when name matches ``_EXPORTS``.

    Raises
    ------
    AttributeError
        If the requested attribute name is not available in this module.
    """
    try:
        module_path = _EXPORTS[name]
    except KeyError as exc:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from exc
    module = import_module(module_path)
    globals()[name] = module
    return module


def __dir__() -> list[str]:  # pragma: no cover - tooling convenience
    return sorted(set(globals()) | set(__all__))
