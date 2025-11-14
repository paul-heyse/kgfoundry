# telemetry/prom.py

## Docstring

```
Prometheus helpers for MCP diagnostics.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any
- from **codeintel_rev.telemetry.otel_metrics** import build_counter, build_histogram
- from **fastapi** import APIRouter
- from **fastapi.responses** import Response
- from **fastapi** import APIRouter
- from **fastapi.responses** import Response

## Definitions

- variable: `ResponseType` (line 15)
- variable: `ResponseType` (line 17)
- variable: `RuntimeAPIRouter` (line 23)
- variable: `RuntimeResponse` (line 24)
- function: `_env_flag` (line 44)
- variable: `RUNS_TOTAL` (line 51)
- variable: `RUN_ERRORS_TOTAL` (line 57)
- variable: `REQUEST_LATENCY_SECONDS` (line 63)
- variable: `STAGE_LATENCY_SECONDS` (line 70)
- variable: `EMBED_BATCH_SIZE` (line 77)
- variable: `EMBED_LATENCY_SECONDS` (line 83)
- variable: `FAISS_SEARCH_LATENCY_SECONDS` (line 89)
- variable: `XTR_SEARCH_LATENCY_SECONDS` (line 95)
- variable: `GATING_DECISIONS_TOTAL` (line 101)
- variable: `RRFK` (line 107)
- variable: `QUERY_AMBIGUITY` (line 113)
- class: `MetricsConfig` (line 121)
- function: `build_metrics_router` (line 127)
- function: `record_run` (line 176)
- function: `record_run_error` (line 181)
- function: `observe_request_latency` (line 186)
- function: `record_stage_latency` (line 191)

## Graph Metrics

- **fan_in**: 9
- **fan_out**: 2
- **cycle_group**: 63

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

EMBED_BATCH_SIZE, EMBED_LATENCY_SECONDS, FAISS_SEARCH_LATENCY_SECONDS, GATING_DECISIONS_TOTAL, MetricsConfig, QUERY_AMBIGUITY, RRFK, XTR_SEARCH_LATENCY_SECONDS, build_metrics_router, observe_request_latency, record_run, record_run_error, record_stage_latency

## Doc Health

- **summary**: Prometheus helpers for MCP diagnostics.
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

## Hotspot

- score: 2.20

## Side Effects

- filesystem

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 194

## Doc Coverage

- `_env_flag` (function): summary=no, examples=no
- `MetricsConfig` (class): summary=yes, examples=no — Configuration container for exposing `/metrics`.
- `build_metrics_router` (function): summary=yes, params=ok, examples=no — Return an APIRouter exposing a compatibility message.
- `record_run` (function): summary=yes, params=mismatch, examples=no — Increment the runs counter for the given tool/status.
- `record_run_error` (function): summary=yes, params=mismatch, examples=no — Increment the run error counter.
- `observe_request_latency` (function): summary=yes, params=mismatch, examples=no — Record request latency for a tool/status pair.
- `record_stage_latency` (function): summary=yes, params=mismatch, examples=no — Record a telemetry stage duration.

## Tags

fastapi, low-coverage, public-api, reexport-hub
