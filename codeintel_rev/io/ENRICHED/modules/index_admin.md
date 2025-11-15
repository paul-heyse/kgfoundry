# app/routers/index_admin.py

## Docstring

```
Admin endpoints for staging, publishing, and rolling back index versions.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **collections.abc** import Mapping
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import TypedDict, cast
- from **fastapi** import APIRouter, Depends, HTTPException, Query, Request
- from **fastapi.responses** import JSONResponse
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.app.scope_store** import ScopeIn
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, collect_asset_attrs
- from **codeintel_rev.observability.run_report** import build_run_report
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 22)
- variable: `router` (line 23)
- function: `_require_admin` (line 28)
- function: `_context` (line 34)
- function: `_find_ledger_path` (line 41)
- function: `get_run_report` (line 54)
- function: `_persist_session_tuning` (line 82)
- function: `status_endpoint` (line 98)
- class: `PublishBody` (line 150)
- class: `TuningBody` (line 213)
- class: `FaissRuntimeTuningBody` (line 262)
- function: `publish_endpoint` (line 314)
- function: `rollback_endpoint` (line 407)
- function: `tuning_endpoint` (line 460)
- function: `faiss_runtime_status` (line 516)
- function: `faiss_runtime_tuning_endpoint` (line 554)
- function: `faiss_runtime_reset_endpoint` (line 633)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 7
- **cycle_group**: 62

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

router

## Doc Health

- **summary**: Admin endpoints for staging, publishing, and rolling back index versions.
- has summary: yes
- param parity: no
- examples present: no

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

- score: 2.33

## Side Effects

- filesystem

## Complexity

- branches: 22
- cyclomatic: 23
- loc: 683

## Doc Coverage

- `_require_admin` (function): summary=no, examples=no
- `_context` (function): summary=no, examples=no
- `_find_ledger_path` (function): summary=no, examples=no
- `get_run_report` (function): summary=yes, params=ok, examples=no — Return structured run report derived from the on-disk ledger.
- `_persist_session_tuning` (function): summary=no, examples=no
- `status_endpoint` (function): summary=yes, params=mismatch, examples=no — Return the current index version and health.
- `PublishBody` (class): summary=yes, examples=no — Request body schema for index publication endpoint.
- `TuningBody` (class): summary=yes, examples=no — Request body schema for runtime tuning endpoint.
- `FaissRuntimeTuningBody` (class): summary=yes, examples=no — Request body schema for FAISS runtime tuning endpoint.
- `publish_endpoint` (function): summary=yes, params=mismatch, examples=no — Stage and publish a new index version, then reload runtimes.

## Tags

fastapi, low-coverage, public-api
