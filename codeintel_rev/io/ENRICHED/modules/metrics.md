# observability/metrics.py

## Docstring

```
Prometheus metrics for hybrid retrieval.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable
- from **kgfoundry_common.prometheus** import build_counter, build_gauge, build_histogram

## Definitions

- variable: `QUERIES_TOTAL` (line 32)
- variable: `QUERY_ERRORS_TOTAL` (line 38)
- variable: `RRF_DURATION_SECONDS` (line 44)
- variable: `CHANNEL_LATENCY_SECONDS` (line 51)
- variable: `INDEX_VERSION_INFO` (line 59)
- variable: `RRF_K` (line 65)
- variable: `BUDGET_DEPTH` (line 70)
- variable: `QUERY_AMBIGUITY` (line 76)
- variable: `DEBUG_BUNDLE_TOTAL` (line 82)
- variable: `RESULTS_TOTAL` (line 87)
- variable: `RECENCY_BOOSTED_TOTAL` (line 92)
- variable: `RECALL_AT_K` (line 97)
- function: `observe_budget_depths` (line 104)
- function: `record_recall` (line 110)
- function: `set_index_version` (line 115)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 50

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

- score: 1.52

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 135

## Doc Coverage

- `observe_budget_depths` (function): summary=yes, params=mismatch, examples=no — Record per-channel depth decisions.
- `record_recall` (function): summary=yes, params=mismatch, examples=no — Record recall@k values produced by offline harnesses.
- `set_index_version` (function): summary=yes, params=ok, examples=no — Expose the current index version for dashboards.

## Tags

low-coverage, public-api, reexport-hub
