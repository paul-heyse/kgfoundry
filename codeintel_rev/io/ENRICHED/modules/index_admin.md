# app/routers/index_admin.py

## Docstring

```
Admin endpoints for staging, publishing, and rolling back index versions.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **collections.abc** import Mapping
- from **contextlib** import suppress
- from **pathlib** import Path
- from **typing** import TypedDict, cast
- from **fastapi** import APIRouter, Depends, HTTPException, Query, Request
- from **fastapi.responses** import JSONResponse
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.app.scope_store** import ScopeIn
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, collect_asset_attrs
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster

## Definitions

- variable: `router` (line 20)
- function: `_require_admin` (line 25)
- function: `_context` (line 31)
- function: `_persist_session_tuning` (line 38)
- function: `status_endpoint` (line 54)
- class: `PublishBody` (line 104)
- class: `TuningBody` (line 167)
- class: `FaissRuntimeTuningBody` (line 211)
- function: `publish_endpoint` (line 263)
- function: `rollback_endpoint` (line 355)
- function: `tuning_endpoint` (line 408)
- function: `faiss_runtime_status` (line 462)
- function: `faiss_runtime_tuning_endpoint` (line 500)
- function: `faiss_runtime_reset_endpoint` (line 579)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 6
- **cycle_group**: 40

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 15
- recent churn 90: 15

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

- score: 2.22

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 629

## Doc Coverage

- `_require_admin` (function): summary=no, examples=no
- `_context` (function): summary=no, examples=no
- `_persist_session_tuning` (function): summary=no, examples=no
- `status_endpoint` (function): summary=yes, params=mismatch, examples=no — Return the current index version and health.
- `PublishBody` (class): summary=yes, examples=no — Request body schema for index publication endpoint.
- `TuningBody` (class): summary=yes, examples=no — Request body schema for runtime tuning endpoint.
- `FaissRuntimeTuningBody` (class): summary=yes, examples=no — Request body schema for FAISS runtime tuning endpoint.
- `publish_endpoint` (function): summary=yes, params=mismatch, examples=no — Stage and publish a new index version, then reload runtimes.
- `rollback_endpoint` (function): summary=yes, params=mismatch, examples=no — Flip ``CURRENT`` to a previously published version.
- `tuning_endpoint` (function): summary=yes, params=mismatch, examples=no — Update runtime tuning knobs (nprobe, fusion weights, etc.).

## Tags

fastapi, low-coverage, public-api
