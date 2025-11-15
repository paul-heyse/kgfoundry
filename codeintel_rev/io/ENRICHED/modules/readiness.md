# app/readiness.py

## Docstring

```
Application readiness checks for Kubernetes health probes.

This module provides comprehensive readiness checks for all critical application
resources including filesystem paths, FAISS indexes, DuckDB catalogs, and
external services (vLLM). The ReadinessProbe class manages these checks and
exposes results via the /readyz endpoint for Kubernetes integration.

Key Components
--------------
CheckResult : dataclass
    Immutable result of a single readiness check with healthy status and detail.
ReadinessProbe : class
    Manages readiness checks across all dependencies with async refresh.

Design Principles
-----------------
- **Comprehensive**: Checks all critical resources (files, directories, services)
- **Non-blocking**: HTTP checks use short timeouts to prevent blocking
- **Graceful Degradation**: Optional resources (SCIP index) don't fail readiness
- **Structured Results**: CheckResult provides JSON-serializable payloads

Example Usage
-------------
During application startup:

>>> # In lifespan() function
>>> readiness = ReadinessProbe(context)
>>> await readiness.initialize()
>>> app.state.readiness = readiness

In readiness endpoint:

>>> # In /readyz handler
>>> results = await readiness.refresh()
>>> return {"ready": all(r.healthy for r in results.values()), "checks": results}

See Also
--------
codeintel_rev.app.config_context : ApplicationContext with configuration
codeintel_rev.app.main : FastAPI application with /readyz endpoint
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import shutil
- from **collections.abc** import Callable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, cast
- from **urllib.parse** import urlparse
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.observability.otel** import as_span, set_current_span_attrs
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import duckdb
- from **(absolute)** import httpx

## Definitions

- variable: `duckdb` (line 63)
- variable: `httpx` (line 64)
- variable: `LOGGER` (line 66)
- variable: `HTTP_HEALTH_TIMEOUT_S` (line 67)
- class: `CheckResult` (line 73)
- class: `ReadinessProbe` (line 111)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 5
- **cycle_group**: 56

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Application readiness checks for Kubernetes health probes.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- app/hypercorn.toml

## Hotspot

- score: 2.44

## Side Effects

- database
- filesystem
- network
- subprocess

## Complexity

- branches: 39
- cyclomatic: 40
- loc: 642

## Doc Coverage

- `CheckResult` (class): summary=yes, examples=yes — Outcome of a single readiness check.
- `ReadinessProbe` (class): summary=yes, examples=yes — Manages readiness checks across core dependencies.

## Tags

low-coverage
