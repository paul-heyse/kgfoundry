# observability/metrics.py

## Docstring

```
Prometheus metrics for hybrid retrieval.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable
- from **codeintel_rev.telemetry.otel_metrics** import build_counter, build_gauge, build_histogram

## Definitions

- variable: `QUERIES_TOTAL` (line 28)
- variable: `QUERY_ERRORS_TOTAL` (line 34)
- variable: `RRF_DURATION_SECONDS` (line 40)
- variable: `CHANNEL_LATENCY_SECONDS` (line 47)
- variable: `INDEX_VERSION_INFO` (line 55)
- variable: `RRF_K` (line 61)
- variable: `BUDGET_DEPTH` (line 66)
- variable: `QUERY_AMBIGUITY` (line 72)
- variable: `DEBUG_BUNDLE_TOTAL` (line 78)
- variable: `RESULTS_TOTAL` (line 83)
- variable: `RECENCY_BOOSTED_TOTAL` (line 88)
- variable: `RECALL_AT_K` (line 93)
- function: `observe_budget_depths` (line 100)
- function: `record_recall` (line 106)
- function: `set_index_version` (line 111)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 55

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

BUDGET_DEPTH, CHANNEL_LATENCY_SECONDS, DEBUG_BUNDLE_TOTAL, INDEX_VERSION_INFO, QUERIES_TOTAL, QUERY_AMBIGUITY, QUERY_ERRORS_TOTAL, RECALL_AT_K, RECENCY_BOOSTED_TOTAL, RESULTS_TOTAL, RRF_DURATION_SECONDS, RRF_K, observe_budget_depths, record_recall, set_index_version

## Doc Health

- **summary**: Prometheus metrics for hybrid retrieval.
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

- score: 1.64

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 131

## Doc Coverage

- `observe_budget_depths` (function): summary=yes, params=mismatch, examples=no — Record per-channel depth decisions.
- `record_recall` (function): summary=yes, params=mismatch, examples=no — Record recall@k values produced by offline harnesses.
- `set_index_version` (function): summary=yes, params=ok, examples=no — Expose the current index version for dashboards.

## Tags

low-coverage, public-api, reexport-hub
