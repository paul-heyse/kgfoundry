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
- from **typing** import TYPE_CHECKING, Protocol
- from **codeintel_rev.observability.otel** import current_trace_id
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import MetricsProvider
- from **kgfoundry_common.observability** import observe_duration
- from **kgfoundry_common.observability** import DurationObservation

## Definitions

- variable: `LOGGER` (line 47)
- function: `_supports_histogram_labels` (line 50)
- class: `_NoopObservation` (line 73)
- class: `Observation` (line 83)
- function: `observe_duration` (line 94)
- function: `_record_exemplar` (line 152)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 139

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

- score: 2.06

## Side Effects

- none detected

## Complexity

- branches: 12
- cyclomatic: 13
- loc: 176

## Doc Coverage

- `_supports_histogram_labels` (function): summary=yes, params=ok, examples=no — Return ``True`` when the histogram exposes label support.
- `_NoopObservation` (class): summary=yes, examples=no — Fallback observation used when metrics cannot be recorded.
- `Observation` (class): summary=yes, examples=no — Protocol describing the helpers provided by metrics observations.
- `observe_duration` (function): summary=yes, params=ok, examples=no — Yield a metrics observation with graceful degradation.
- `_record_exemplar` (function): summary=yes, params=mismatch, examples=no — Attach exemplars to the duration histogram when supported.

## Tags

low-coverage, public-api
