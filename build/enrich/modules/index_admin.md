# app/routers/index_admin.py

## Docstring

```
Admin endpoints for staging, publishing, and rolling back index versions.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **collections.abc** import Mapping
- from **pathlib** import Path
- from **typing** import TypedDict, cast
- from **fastapi** import APIRouter, Depends, HTTPException, Query, Request
- from **fastapi.responses** import JSONResponse
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.app.scope_store** import ScopeIn
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 20)
- variable: `router` (line 21)
- function: `_require_admin` (line 26)
- function: `_context` (line 32)
- function: `_persist_session_tuning` (line 39)
- function: `status_endpoint` (line 55)
- class: `PublishBody` (line 107)
- class: `TuningBody` (line 162)
- class: `FaissRuntimeTuningBody` (line 211)
- function: `publish_endpoint` (line 263)
- function: `rollback_endpoint` (line 350)
- function: `tuning_endpoint` (line 403)
- function: `faiss_runtime_status` (line 459)
- function: `faiss_runtime_tuning_endpoint` (line 497)
- function: `faiss_runtime_reset_endpoint` (line 576)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 6
- **cycle_group**: 120

## Declared Exports (__all__)

router

## Doc Metrics

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

## Hotspot Score

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 626

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
