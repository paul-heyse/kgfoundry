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
- from **(absolute)** import duckdb
- from **(absolute)** import httpx

## Definitions

- variable: `duckdb` (line 60)
- variable: `httpx` (line 61)
- variable: `HTTP_HEALTH_TIMEOUT_S` (line 63)
- class: `CheckResult` (line 69)
- class: `ReadinessProbe` (line 107)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 37

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

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

- score: 2.27

## Side Effects

- database
- filesystem
- network
- subprocess

## Complexity

- branches: 35
- cyclomatic: 36
- loc: 626

## Doc Coverage

- `CheckResult` (class): summary=yes, examples=yes — Outcome of a single readiness check.
- `ReadinessProbe` (class): summary=yes, examples=yes — Manages readiness checks across core dependencies.

## Tags

low-coverage
