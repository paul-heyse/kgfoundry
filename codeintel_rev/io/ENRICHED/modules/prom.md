# telemetry/prom.py

## Docstring

```
Prometheus helpers for MCP diagnostics.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **dataclasses** import dataclass
- from **fastapi** import APIRouter
- from **fastapi.responses** import Response
- from **prometheus_client** import CONTENT_TYPE_LATEST, generate_latest
- from **kgfoundry_common.prometheus** import CollectorRegistry, build_counter, build_histogram, get_default_registry

## Definitions

- variable: `APIRouter` (line 12)
- variable: `Response` (line 13)
- variable: `CONTENT_TYPE_LATEST` (line 18)
- function: `generate_latest` (line 20)
- function: `_env_flag` (line 62)
- variable: `RUNS_TOTAL` (line 69)
- variable: `RUN_ERRORS_TOTAL` (line 75)
- variable: `REQUEST_LATENCY_SECONDS` (line 81)
- variable: `STAGE_LATENCY_SECONDS` (line 88)
- class: `MetricsConfig` (line 97)
- function: `build_metrics_router` (line 104)
- function: `record_run` (line 169)
- function: `record_run_error` (line 174)
- function: `observe_request_latency` (line 179)
- function: `record_stage_latency` (line 184)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 0
- **cycle_group**: 42

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

MetricsConfig, build_metrics_router, observe_request_latency, record_run, record_run_error, record_stage_latency

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

- score: 1.98

## Side Effects

- filesystem

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 187

## Doc Coverage

- `generate_latest` (function): summary=yes, params=ok, examples=no — Return placeholder metrics when prometheus_client is unavailable.
- `_env_flag` (function): summary=no, examples=no
- `MetricsConfig` (class): summary=yes, examples=no — Configuration container for exposing `/metrics`.
- `build_metrics_router` (function): summary=yes, params=ok, examples=no — Return an APIRouter exposing the Prometheus scrape endpoint.
- `record_run` (function): summary=yes, params=mismatch, examples=no — Increment the runs counter for the given tool/status.
- `record_run_error` (function): summary=yes, params=mismatch, examples=no — Increment the run error counter.
- `observe_request_latency` (function): summary=yes, params=mismatch, examples=no — Record request latency for a tool/status pair.
- `record_stage_latency` (function): summary=yes, params=mismatch, examples=no — Record a telemetry stage duration.

## Tags

fastapi, low-coverage, public-api
