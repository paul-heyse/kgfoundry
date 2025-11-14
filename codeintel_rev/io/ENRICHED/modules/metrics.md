# observability/metrics.py

## Docstring

```
Telemetry metrics registry and OpenTelemetry Meter bootstrap.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **(absolute)** import threading
- from **collections.abc** import Iterable
- from **dataclasses** import dataclass, field
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING
- from **codeintel_rev.telemetry.otel_metrics** import build_counter, build_gauge, build_histogram
- from **kgfoundry_common.logging** import get_logger
- from **opentelemetry.sdk.metrics.export** import MetricReader
- from **opentelemetry.sdk.metrics.view** import View
- from **opentelemetry.sdk.resources** import Resource
- from **prometheus_client** import start_http_server

## Definitions

- variable: `LOGGER` (line 21)
- class: `_MetricsState` (line 25)
- function: `_env_flag` (line 41)
- function: `_import_module` (line 48)
- function: `_build_metric_views` (line 67)
- function: `_build_prometheus_reader` (line 113)
- function: `_start_prometheus_http_server` (line 127)
- function: `_load_metrics_modules` (line 158)
- function: `_build_otlp_reader` (line 179)
- function: `install_metrics_provider` (line 211)
- variable: `QUERIES_TOTAL` (line 281)
- variable: `QUERY_ERRORS_TOTAL` (line 287)
- variable: `RRF_DURATION_SECONDS` (line 293)
- variable: `CHANNEL_LATENCY_SECONDS` (line 300)
- variable: `INDEX_VERSION_INFO` (line 308)
- variable: `RRF_K` (line 314)
- variable: `BUDGET_DEPTH` (line 319)
- variable: `QUERY_AMBIGUITY` (line 325)
- variable: `DEBUG_BUNDLE_TOTAL` (line 331)
- variable: `RESULTS_TOTAL` (line 336)
- variable: `RECENCY_BOOSTED_TOTAL` (line 341)
- variable: `RECALL_AT_K` (line 346)
- function: `observe_budget_depths` (line 353)
- function: `record_recall` (line 359)
- function: `set_index_version` (line 364)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 9

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

BUDGET_DEPTH, CHANNEL_LATENCY_SECONDS, DEBUG_BUNDLE_TOTAL, INDEX_VERSION_INFO, QUERIES_TOTAL, QUERY_AMBIGUITY, QUERY_ERRORS_TOTAL, RECALL_AT_K, RECENCY_BOOSTED_TOTAL, RESULTS_TOTAL, RRF_DURATION_SECONDS, RRF_K, install_metrics_provider, observe_budget_depths, record_recall, set_index_version

## Doc Health

- **summary**: Telemetry metrics registry and OpenTelemetry Meter bootstrap.
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

- score: 2.41

## Side Effects

- filesystem

## Complexity

- branches: 44
- cyclomatic: 45
- loc: 384

## Doc Coverage

- `_MetricsState` (class): summary=yes, examples=no — Thread-safe metrics provider state.
- `_env_flag` (function): summary=no, examples=no
- `_import_module` (function): summary=yes, params=ok, examples=no — Import a module by name, returning None if unavailable.
- `_build_metric_views` (function): summary=no, examples=no
- `_build_prometheus_reader` (function): summary=no, examples=no
- `_start_prometheus_http_server` (function): summary=yes, params=ok, examples=no — Start Prometheus HTTP server for metrics scraping (idempotent).
- `_load_metrics_modules` (function): summary=yes, params=ok, examples=no — Load all required metrics SDK modules.
- `_build_otlp_reader` (function): summary=yes, params=ok, examples=no — Build OTLP metric reader if available.
- `install_metrics_provider` (function): summary=yes, params=ok, examples=no — Install a global MeterProvider with OTLP + Prometheus readers.
- `observe_budget_depths` (function): summary=yes, params=mismatch, examples=no — Record per-channel depth decisions.

## Tags

low-coverage, public-api, reexport-hub
