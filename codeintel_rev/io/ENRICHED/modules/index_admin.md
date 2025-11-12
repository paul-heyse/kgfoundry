# app/routers/index_admin.py

## Docstring

```
Admin endpoints for staging, publishing, and rolling back index versions.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **pathlib** import Path
- from **typing** import TypedDict, cast
- from **fastapi** import APIRouter, Depends, HTTPException, Query, Request
- from **fastapi.responses** import JSONResponse
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets
- from **codeintel_rev.mcp_server.schemas** import ScopeIn
- from **codeintel_rev.runtime.factory_adjustment** import DefaultFactoryAdjuster
- from **kgfoundry_common.logging** import get_logger

## Definitions

- function: `_require_admin` (line 25)
- function: `_context` (line 31)
- function: `_persist_session_tuning` (line 38)
- function: `status_endpoint` (line 52)
- class: `PublishBody` (line 104)
- class: `TuningBody` (line 159)
- class: `FaissRuntimeTuningBody` (line 208)
- function: `publish_endpoint` (line 260)
- function: `rollback_endpoint` (line 347)
- function: `tuning_endpoint` (line 400)
- function: `faiss_runtime_status` (line 456)
- function: `faiss_runtime_tuning_endpoint` (line 494)
- function: `faiss_runtime_reset_endpoint` (line 573)

## Tags

fastapi, overlay-needed, public-api
