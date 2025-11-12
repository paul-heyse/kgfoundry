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
- from **(absolute)** import asyncio
- from **codeintel_rev.app.scope_store** import SupportsAsyncRedis
- from **codeintel_rev.io.hybrid_search** import HybridSearchEngine
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- function: `_infer_index_root` (line 101)
- function: `_build_factory_adjuster` (line 131)
- function: `_assign_frozen` (line 167)
- function: `_faiss_module` (line 172)
- function: `_import_faiss_manager_cls` (line 188)
- function: `_import_faiss_runtime_opts_cls` (line 200)
- function: `_faiss_runtime_options_from_index` (line 212)
- function: `_import_hybrid_engine_cls` (line 253)
- function: `_import_xtr_index_cls` (line 270)
- function: `_require_dependency` (line 287)
- function: `_ensure_path_exists` (line 346)
- class: `ResolvedPaths` (line 406)
- function: `resolve_application_paths` (line 462)
- function: `_resolve` (line 523)
- class: `_FaissRuntimeState` (line 578)
- function: `__init__` (line 583)
- class: `_ContextRuntimeState` (line 590)
- function: `attach_observer` (line 602)
- function: `attach_adjuster` (line 608)
- function: `iter_cells` (line 614)
- class: `ApplicationContext` (line 630)
- function: `__post_init__` (line 731)
- function: `create` (line 744)
- function: `_iter_runtime_cells` (line 887)
- function: `reload_indices` (line 897)
- function: `_update_index_version_metrics` (line 915)
- function: `apply_factory_adjuster` (line 924)
- function: `get_hybrid_engine` (line 935)
- function: `_factory` (line 949)
- function: `get_offline_recall_evaluator` (line 958)
- function: `get_coderank_faiss_manager` (line 989)
- function: `_factory` (line 1022)
- function: `get_xtr_index` (line 1035)
- function: `_factory` (line 1057)
- function: `_build_coderank_faiss_manager` (line 1082)
- function: `_build_xtr_index` (line 1150)
- function: `_build_hybrid_engine` (line 1186)
- function: `ensure_faiss_ready` (line 1207)
- function: `open_catalog` (line 1281)
- function: `with_overrides` (line 1327)
- function: `_component_value` (line 1394)
- function: `close_all_runtimes` (line 1409)

## Tags

overlay-needed, public-api
