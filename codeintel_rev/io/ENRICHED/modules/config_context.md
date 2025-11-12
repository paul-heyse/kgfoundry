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
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.observability** import metrics
- from **codeintel_rev.runtime** import NullRuntimeCellObserver, RuntimeCell, RuntimeCellObserver
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster, FactoryAdjuster, NoopFactoryAdjuster
- from **codeintel_rev.typing** import gate_import
- from **kgfoundry_common.errors** import ConfigurationError
- from **kgfoundry_common.logging** import get_logger
- from **collections.abc** import Iterator
- from **codeintel_rev.app.scope_store** import SupportsAsyncRedis
- from **codeintel_rev.io.hybrid_search** import HybridSearchEngine
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `HybridSearchEngine` (line 90)
- variable: `XTRIndex` (line 91)
- variable: `LOGGER` (line 93)
- function: `_infer_index_root` (line 99)
- function: `_build_factory_adjuster` (line 129)
- function: `_assign_frozen` (line 165)
- function: `_faiss_module` (line 170)
- function: `_import_faiss_manager_cls` (line 186)
- function: `_import_faiss_runtime_opts_cls` (line 198)
- function: `_faiss_runtime_options_from_index` (line 210)
- function: `_import_hybrid_engine_cls` (line 251)
- function: `_import_xtr_index_cls` (line 268)
- function: `_require_dependency` (line 285)
- function: `_ensure_path_exists` (line 344)
- class: `ResolvedPaths` (line 404)
- function: `resolve_application_paths` (line 460)
- variable: `T` (line 573)
- class: `_FaissRuntimeState` (line 576)
- class: `_ContextRuntimeState` (line 588)
- class: `ApplicationContext` (line 628)

## Dependency Graph

- **fan_in**: 20
- **fan_out**: 18
- **cycle_group**: 42

## Declared Exports (__all__)

ApplicationContext, ResolvedPaths, resolve_application_paths

## Tags

public-api
