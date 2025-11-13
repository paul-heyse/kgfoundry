# telemetry/prom.py

## Docstring

```
Prometheus helpers for MCP diagnostics.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **kgfoundry_common.prometheus** import CollectorRegistry, build_counter, build_histogram, get_default_registry
- from **fastapi** import APIRouter
- from **fastapi.responses** import Response
- from **fastapi** import APIRouter
- from **fastapi.responses** import Response
- from **prometheus_client** import CONTENT_TYPE_LATEST
- from **prometheus_client** import generate_latest

## Definitions

- variable: `RuntimeAPIRouter` (line 24)
- variable: `RuntimeResponse` (line 25)
- class: `_GenerateLatest` (line 28)
- variable: `PROM_CONTENT_TYPE` (line 36)
- function: `_prometheus_generate_latest` (line 38)
- function: `_prometheus_generate_latest` (line 48)
- variable: `CONTENT_TYPE_LATEST` (line 54)
- function: `generate_latest` (line 57)
- function: `_env_flag` (line 93)
- variable: `RUNS_TOTAL` (line 100)
- variable: `RUN_ERRORS_TOTAL` (line 106)
- variable: `REQUEST_LATENCY_SECONDS` (line 112)
- variable: `STAGE_LATENCY_SECONDS` (line 119)
- class: `MetricsConfig` (line 128)
- function: `build_metrics_router` (line 135)
- function: `record_run` (line 197)
- function: `record_run_error` (line 202)
- function: `observe_request_latency` (line 207)
- function: `record_stage_latency` (line 212)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 1
- **cycle_group**: 44

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

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

- score: 2.14

## Side Effects

- filesystem

## Complexity

- branches: 13
- cyclomatic: 14
- loc: 215

## Doc Coverage

- `_GenerateLatest` (class): summary=no, examples=no
- `_prometheus_generate_latest` (function): summary=no, examples=no
- `_prometheus_generate_latest` (function): summary=no, examples=no
- `generate_latest` (function): summary=yes, params=ok, examples=no — Proxy to prometheus_client.generate_latest with graceful fallback.
- `_env_flag` (function): summary=no, examples=no
- `MetricsConfig` (class): summary=yes, examples=no — Configuration container for exposing `/metrics`.
- `build_metrics_router` (function): summary=yes, params=ok, examples=no — Return an APIRouter exposing the Prometheus scrape endpoint.
- `record_run` (function): summary=yes, params=mismatch, examples=no — Increment the runs counter for the given tool/status.
- `record_run_error` (function): summary=yes, params=mismatch, examples=no — Increment the run error counter.
- `observe_request_latency` (function): summary=yes, params=mismatch, examples=no — Record request latency for a tool/status pair.

## Tags

fastapi, low-coverage, public-api
