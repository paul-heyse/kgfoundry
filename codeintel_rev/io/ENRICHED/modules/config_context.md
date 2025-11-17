# app/config_context.py

## Docstring

```
Application-level configuration context manager.

This module provides centralized configuration lifecycle management for the
CodeIntel MCP application. Instead of loading settings repeatedly from environment
variables on each request, configuration is loaded exactly once during FastAPI
application startup and shared across all request handlers via explicit dependency
injection.

Key Components
--------------
ResolvedPaths : dataclass
    Canonicalized absolute filesystem paths for all application resources.
ApplicationContext : dataclass
    Application-wide context holding configuration and long-lived clients.
resolve_application_paths : function
    Validates and resolves all configured paths relative to repository root.

Design Principles
-----------------
- **Load Once**: Configuration parsed from environment exactly once at startup
- **Explicit Injection**: Context passed as parameter (no global state)
- **Fail-Fast**: Invalid configuration prevents application startup
- **Immutable**: Settings frozen after creation (thread-safe)
- **RFC 9457**: All errors use Problem Details format

Example Usage
-------------
During FastAPI application startup:

>>> # In lifespan() function
>>> context = ApplicationContext.create()
>>> app.state.context = context

In request handlers:

>>> # In MCP tool wrapper
>>> context = request.app.state.context
>>> files_adapter.list_paths(context, path="src")

See Also
--------
codeintel_rev.app.readiness : Readiness probe system for health checks
codeintel_rev.config.settings : Settings dataclasses and environment loading
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **threading** import Lock
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Any, TypeVar, cast
- from **(absolute)** import numpy
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.scope_store** import ScopeStore
- from **codeintel_rev.config.settings** import IndexConfig, Settings, load_settings
- from **codeintel_rev.errors** import RuntimeLifecycleError, RuntimeUnavailableError
- from **codeintel_rev.evaluation.offline_recall** import OfflineRecallEvaluator
- from **codeintel_rev.indexing.index_lifecycle** import IndexLifecycleManager
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.faiss_manager** import FAISSManager, FAISSRuntimeOptions
- from **codeintel_rev.io.git_client** import AsyncGitClient, GitClient
- from **codeintel_rev.io.vllm_client** import VLLMClient, build_vllm_client
- from **codeintel_rev.runtime** import NullRuntimeCellObserver, RuntimeCell, RuntimeCellObserver
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster, FactoryAdjuster, NoopFactoryAdjuster
- from **codeintel_rev.typing** import gate_import
- from **kgfoundry_common.errors** import ConfigurationError
- from **collections.abc** import Iterator
- from **codeintel_rev.app.scope_store** import SupportsAsyncRedis
- from **codeintel_rev.io.hybrid_search** import HybridSearchEngine
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `HybridSearchEngine` (line 90)
- variable: `XTRIndex` (line 91)
- function: `_infer_index_root` (line 101)
- function: `_build_factory_adjuster` (line 131)
- function: `_build_faiss_manager` (line 164)
- function: `_build_scope_store` (line 198)
- function: `_build_git_clients` (line 224)
- function: `_assign_frozen` (line 245)
- function: `_faiss_module` (line 250)
- function: `_import_faiss_manager_cls` (line 266)
- function: `_import_faiss_runtime_opts_cls` (line 278)
- function: `_faiss_runtime_options_from_index` (line 290)
- function: `_import_hybrid_engine_cls` (line 330)
- function: `_import_xtr_index_cls` (line 347)
- function: `_require_dependency` (line 364)
- function: `_ensure_path_exists` (line 423)
- class: `ResolvedPaths` (line 483)
- function: `resolve_application_paths` (line 542)
- variable: `T` (line 654)
- class: `_FaissRuntimeState` (line 657)
- class: `_ContextRuntimeState` (line 668)
- class: `ApplicationContext` (line 708)

## Graph Metrics

- **fan_in**: 23
- **fan_out**: 16
- **cycle_group**: 28

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 44
- recent churn 90: 44

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

ApplicationContext, ResolvedPaths, resolve_application_paths

## Doc Health

- **summary**: Application-level configuration context manager.
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

- score: 3.27

## Side Effects

- filesystem
- network

## Complexity

- branches: 61
- cyclomatic: 62
- loc: 1437

## Doc Coverage

- `_infer_index_root` (function): summary=yes, params=ok, examples=no — Return the directory that stores versioned index assets.
- `_build_factory_adjuster` (function): summary=yes, params=ok, examples=no — Return a DefaultFactoryAdjuster derived from settings.
- `_build_faiss_manager` (function): summary=yes, params=ok, examples=no — Construct and log the FAISS manager for the main index.
- `_build_scope_store` (function): summary=yes, params=ok, examples=no — Return the session scope store backed by redis.asyncio.
- `_build_git_clients` (function): summary=yes, params=ok, examples=no — Initialize Git clients for blame and history operations.
- `_assign_frozen` (function): summary=yes, params=mismatch, examples=no — Assign attribute on a frozen dataclass instance.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the cached FAISS manager module.
- `_import_faiss_manager_cls` (function): summary=yes, params=ok, examples=no — Import ``FAISSManager`` lazily to keep module import costs low.
- `_import_faiss_runtime_opts_cls` (function): summary=yes, params=ok, examples=no — Return the FAISS runtime options dataclass.
- `_faiss_runtime_options_from_index` (function): summary=yes, params=ok, examples=no — Materialize FAISS runtime options from the structured index config.

## Tags

low-coverage, public-api
