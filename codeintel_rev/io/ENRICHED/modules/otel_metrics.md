# telemetry/otel_metrics.py

## Docstring

```
Compatibility layer exposing Prometheus-like helpers backed by OpenTelemetry.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **threading** import Lock
- from **opentelemetry** import metrics
- from **opentelemetry.metrics** import CallbackOptions, Observation

## Definitions

- class: `CounterHandle` (line 24)
- class: `HistogramHandle` (line 38)
- class: `CounterLike` (line 52)
- class: `HistogramLike` (line 95)
- class: `_GaugeEntry` (line 147)
- class: `GaugeHandle` (line 152)
- class: `GaugeLike` (line 166)
- function: `build_counter` (line 261)
- function: `build_histogram` (line 276)
- function: `build_gauge` (line 300)

## Graph Metrics

- **fan_in**: 9
- **fan_out**: 0
- **cycle_group**: 39

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

CounterLike, GaugeLike, HistogramLike, build_counter, build_gauge, build_histogram

## Doc Health

- **summary**: Compatibility layer exposing Prometheus-like helpers backed by OpenTelemetry.
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

- score: 2.35

## Side Effects

- none detected

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 320

## Doc Coverage

- `CounterHandle` (class): summary=yes, examples=no — Lightweight handle mutating a counter with pre-bound attributes.
- `HistogramHandle` (class): summary=yes, examples=no — Histogram view that records values with pre-bound attributes.
- `CounterLike` (class): summary=yes, examples=no — Counter facade exposing `.inc()` and `.labels().inc()`.
- `HistogramLike` (class): summary=yes, examples=no — Histogram facade exposing `.observe()` and `.labels().observe()`.
- `_GaugeEntry` (class): summary=no, examples=no
- `GaugeHandle` (class): summary=yes, examples=no — Gauge handle supporting ``set`` semantics.
- `GaugeLike` (class): summary=yes, examples=no — Gauge facade backed by an ObservableGauge.
- `build_counter` (function): summary=yes, params=mismatch, examples=no — Return a CounterLike backed by OpenTelemetry.
- `build_histogram` (function): summary=yes, params=mismatch, examples=no — Return a HistogramLike backed by OpenTelemetry.
- `build_gauge` (function): summary=yes, params=mismatch, examples=no — Return an ObservableGauge facade.

## Tags

low-coverage, public-api
