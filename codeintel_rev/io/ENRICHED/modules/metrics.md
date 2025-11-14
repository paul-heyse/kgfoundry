# observability/metrics.py

## Docstring

```
Telemetry metrics registry and OpenTelemetry Meter bootstrap.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **collections.abc** import Iterable
- from **typing** import TYPE_CHECKING, Any
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.telemetry.otel_metrics** import build_counter, build_gauge, build_histogram
- from **opentelemetry.sdk.resources** import Resource
- from **prometheus_client** import start_http_server

## Definitions

- variable: `Resource` (line 17)
- variable: `LOGGER` (line 19)
- function: `_env_flag` (line 29)
- function: `_import_module` (line 36)
- function: `_build_metric_views` (line 43)
- function: `_build_prometheus_reader` (line 82)
- function: `_start_prometheus_http_server` (line 96)
- function: `install_metrics_provider` (line 114)
- variable: `QUERIES_TOTAL` (line 181)
- variable: `QUERY_ERRORS_TOTAL` (line 187)
- variable: `RRF_DURATION_SECONDS` (line 193)
- variable: `CHANNEL_LATENCY_SECONDS` (line 200)
- variable: `INDEX_VERSION_INFO` (line 208)
- variable: `RRF_K` (line 214)
- variable: `BUDGET_DEPTH` (line 219)
- variable: `QUERY_AMBIGUITY` (line 225)
- variable: `DEBUG_BUNDLE_TOTAL` (line 231)
- variable: `RESULTS_TOTAL` (line 236)
- variable: `RECENCY_BOOSTED_TOTAL` (line 241)
- variable: `RECALL_AT_K` (line 246)
- function: `observe_budget_depths` (line 253)
- function: `record_recall` (line 259)
- function: `set_index_version` (line 264)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 11

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

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

- score: 2.31

## Side Effects

- filesystem

## Complexity

- branches: 31
- cyclomatic: 32
- loc: 284

## Doc Coverage

- `_env_flag` (function): summary=no, examples=no
- `_import_module` (function): summary=no, examples=no
- `_build_metric_views` (function): summary=no, examples=no
- `_build_prometheus_reader` (function): summary=no, examples=no
- `_start_prometheus_http_server` (function): summary=no, examples=no
- `install_metrics_provider` (function): summary=yes, params=mismatch, examples=no — Install a global MeterProvider with OTLP + Prometheus readers.
- `observe_budget_depths` (function): summary=yes, params=mismatch, examples=no — Record per-channel depth decisions.
- `record_recall` (function): summary=yes, params=mismatch, examples=no — Record recall@k values produced by offline harnesses.
- `set_index_version` (function): summary=yes, params=ok, examples=no — Expose the current index version for dashboards.

## Tags

low-coverage, public-api, reexport-hub
