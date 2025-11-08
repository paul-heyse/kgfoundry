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

# Protect lazy initialization so concurrent callers do not instantiate the
# ApplicationContext multiple times.
_CONTEXT_LOCK = Lock()
_CACHED_CONTEXT: ApplicationContext | None = None


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
    global _CACHED_CONTEXT  # noqa: PLW0603 - module-level cache protected by lock
    if _CACHED_CONTEXT is None:
        with _CONTEXT_LOCK:
            if _CACHED_CONTEXT is None:
                _CACHED_CONTEXT = ApplicationContext.create()
    return _CACHED_CONTEXT


def reset_service_context() -> None:
    """Clear the cached :class:`ApplicationContext`.

    Primarily intended for tests or scripts that mutate environment variables
    between runs. The next call to :func:`get_service_context` will recreate the
    context from the latest configuration.
    """
    global _CACHED_CONTEXT  # noqa: PLW0603 - module-level cache protected by lock
    with _CONTEXT_LOCK:
        _CACHED_CONTEXT = None
