# mcp_server/service_context.py

## Docstring

```
Cached application context for MCP tool adapters.

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
```

## Imports

- from **__future__** import annotations
- from **threading** import Lock
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- function: `_get_cached_context` (line 31)
- function: `_set_cached_context` (line 42)
- function: `get_service_context` (line 47)
- function: `reset_service_context` (line 71)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 77

## Declared Exports (__all__)

get_service_context, reset_service_context

## Tags

public-api
