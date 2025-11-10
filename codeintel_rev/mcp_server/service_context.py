"""Cached application context for MCP tool adapters.

This module exposes a small facade that lazily creates and caches the
:class:`~codeintel_rev.app.config_context.ApplicationContext` used by the MCP
server tool adapters. The cached context reuses the same configuration and
path-resolution logic as the FastAPI app and readiness probes because it
ultimately delegates creation to :meth:`ApplicationContext.create`, which reads
environment overrides and resolves paths via
:func:`~codeintel_rev.app.config_context.resolve_application_paths`.

The cache ensures heavy resources such as the FAISS index manager and DuckDB
catalog are only initialized once per process. Tests and administrative scripts
can call :func:`reset_service_context` to clear the cache when environment
variables change or when they need fresh dependencies.
"""

from __future__ import annotations

from threading import Lock

from codeintel_rev.app.config_context import ApplicationContext

__all__ = ["get_service_context", "reset_service_context"]

_CONTEXT_CACHE: dict[str, ApplicationContext | None] = {"value": None}
# Protect lazy initialization so concurrent callers do not instantiate the
# ApplicationContext multiple times.
_CONTEXT_LOCK = Lock()


def _get_cached_context() -> ApplicationContext | None:
    """Return the cached context instance, if any.

    Returns
    -------
    ApplicationContext | None
        Previously cached context or ``None`` when not initialized.
    """
    return _CONTEXT_CACHE["value"]


def _set_cached_context(context: ApplicationContext | None) -> None:
    """Update the cached context reference."""
    _CONTEXT_CACHE["value"] = context


def get_service_context() -> ApplicationContext:
    """Return the cached :class:`ApplicationContext` instance.

    The first invocation creates the context via
    :meth:`ApplicationContext.create`. Subsequent calls return the cached
    instance so that adapters share the same settings, resolved paths, and
    long-lived clients.

    Returns
    -------
    ApplicationContext
        Cached application context instance with settings, resolved paths,
        and long-lived clients (FAISS manager, vLLM client, DuckDB catalog).
    """
    cached = _get_cached_context()
    if cached is None:
        with _CONTEXT_LOCK:
            cached = _get_cached_context()
            if cached is None:
                cached = ApplicationContext.create()
                _set_cached_context(cached)
    return cached


def reset_service_context() -> None:
    """Clear the cached :class:`ApplicationContext`.

    Primarily intended for tests or scripts that mutate environment variables
    between runs. The next call to :func:`get_service_context` will recreate the
    context from the latest configuration.
    """
    with _CONTEXT_LOCK:
        _set_cached_context(None)
