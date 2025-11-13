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

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 109

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 10
- recent churn 90: 10

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

get_service_context, reset_service_context

## Doc Health

- **summary**: Cached application context for MCP tool adapters.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.36

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 80

## Doc Coverage

- `_get_cached_context` (function): summary=yes, params=ok, examples=no — Return the cached context instance, if any.
- `_set_cached_context` (function): summary=yes, params=mismatch, examples=no — Update the cached context reference.
- `get_service_context` (function): summary=yes, params=ok, examples=no — Return the cached :class:`ApplicationContext` instance.
- `reset_service_context` (function): summary=yes, params=ok, examples=no — Clear the cached :class:`ApplicationContext`.

## Tags

low-coverage, public-api
