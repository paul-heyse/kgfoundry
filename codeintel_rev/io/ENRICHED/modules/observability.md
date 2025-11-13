# mcp_server/common/observability.py

## Docstring

```
Unified observability helpers for CodeIntel MCP adapters.

The adapters previously duplicated more than sixty lines of metrics boilerplate.
This module centralises the logic, delegates to :mod:`kgfoundry_common`
observability primitives, and keeps behaviour backward compatible with existing
Prometheus dashboards.

Examples
--------
Basic usage in an adapter:

>>> from codeintel_rev.mcp_server.common.observability import observe_duration
>>> with observe_duration("search", "text_search") as observation:
...     result = perform_search()
...     observation.mark_success()

Graceful degradation when metrics are unavailable:

>>> with observe_duration("semantic_search", "codeintel_mcp") as observation:
...     try:
...         perform_semantic_search()
...         observation.mark_success()
...     except RuntimeError:
...         observation.mark_error()
...         raise
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator
- from **contextlib** import contextmanager
- from **typing** import Protocol
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import MetricsProvider
- from **kgfoundry_common.observability** import observe_duration

## Definitions

- variable: `LOGGER` (line 43)
- function: `_supports_histogram_labels` (line 46)
- class: `_NoopObservation` (line 69)
- class: `Observation` (line 79)
- function: `observe_duration` (line 90)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 123

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

Observation, observe_duration

## Doc Health

- **summary**: Unified observability helpers for CodeIntel MCP adapters.
- has summary: yes
- param parity: yes
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

- score: 1.81

## Side Effects

- none detected

## Complexity

- branches: 6
- cyclomatic: 7
- loc: 142

## Doc Coverage

- `_supports_histogram_labels` (function): summary=yes, params=ok, examples=no — Return ``True`` when the histogram exposes label support.
- `_NoopObservation` (class): summary=yes, examples=no — Fallback observation used when metrics cannot be recorded.
- `Observation` (class): summary=yes, examples=no — Protocol describing the helpers provided by metrics observations.
- `observe_duration` (function): summary=yes, params=ok, examples=no — Yield a metrics observation with graceful degradation.

## Tags

low-coverage, public-api
