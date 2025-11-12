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
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, cast
- from **urllib.parse** import urlparse
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import duckdb
- from **(absolute)** import httpx

## Definitions

- class: `CheckResult` (line 71)
- function: `as_payload` (line 95)
- class: `ReadinessProbe` (line 109)
- function: `__init__` (line 150)
- function: `initialize` (line 155)
- function: `refresh` (line 168)
- function: `shutdown` (line 196)
- function: `snapshot` (line 209)
- function: `_run_checks` (line 237)
- function: `check_directory` (line 288)
- function: `check_file` (line 326)
- function: `_check_duckdb_catalog` (line 376)
- function: `_check_xtr_artifacts` (line 422)
- function: `_duckdb_table_exists` (line 445)
- function: `_duckdb_index_exists` (line 469)
- function: `_check_search_tools` (line 492)
- function: `check_vllm_connection` (line 515)
- function: `_check_vllm_inprocess` (line 528)
- function: `_check_vllm_http` (line 553)

## Tags

overlay-needed
