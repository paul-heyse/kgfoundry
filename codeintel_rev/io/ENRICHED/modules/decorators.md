# telemetry/decorators.py

## Docstring

```
Decorators for consistent span/timeline instrumentation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import functools
- from **(absolute)** import importlib
- from **(absolute)** import inspect
- from **collections.abc** import Callable, Iterator, Mapping
- from **contextlib** import contextmanager, nullcontext
- from **time** import perf_counter
- from **typing** import TypeVar
- from **opentelemetry** import trace
- from **opentelemetry.trace** import Span, SpanKind, Status, StatusCode
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.telemetry.context** import attach_context_attrs, set_request_stage
- from **codeintel_rev.telemetry.prom** import record_stage_latency

## Definitions

- variable: `F` (line 20)
- variable: `TRACER` (line 30)
- function: `_emit_checkpoint` (line 33)
- function: `_set_span_attributes` (line 48)
- function: `_span_scope` (line 59)
- function: `_record_exception` (line 81)
- function: `span_context` (line 87)
- function: `trace_span` (line 170)
- function: `trace_step` (line 321)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 4
- **cycle_group**: 47

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

span_context, trace_span, trace_step

## Doc Health

- **summary**: Decorators for consistent span/timeline instrumentation.
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

- score: 2.49

## Side Effects

- none detected

## Complexity

- branches: 25
- cyclomatic: 26
- loc: 370

## Doc Coverage

- `_emit_checkpoint` (function): summary=no, examples=no
- `_set_span_attributes` (function): summary=no, examples=no
- `_span_scope` (function): summary=no, examples=no
- `_record_exception` (function): summary=no, examples=no
- `span_context` (function): summary=yes, params=ok, examples=no — Create a span/timeline scope for the wrapped block.
- `trace_span` (function): summary=yes, params=ok, examples=no — Wrap callable execution in an OpenTelemetry span + timeline step.
- `trace_step` (function): summary=yes, params=ok, examples=no — Specialized decorator that records checkpoints for pipeline stages.

## Tags

low-coverage, public-api
