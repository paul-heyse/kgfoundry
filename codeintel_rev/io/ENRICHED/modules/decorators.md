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
- from **(absolute)** import logging
- from **collections.abc** import Awaitable, Callable, Iterator, Mapping
- from **contextlib** import contextmanager, nullcontext
- from **dataclasses** import dataclass, field
- from **time** import perf_counter
- from **types** import SimpleNamespace
- from **typing** import TYPE_CHECKING, TypeVar, cast
- from **opentelemetry** import trace
- from **opentelemetry.trace** import Span, SpanKind, Status, StatusCode
- from **opentelemetry.trace** import Span
- from **opentelemetry.trace** import SpanKind
- from **opentelemetry.trace** import Status
- from **opentelemetry.trace** import StatusCode
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.telemetry** import steps
- from **codeintel_rev.telemetry.context** import attach_context_attrs, set_request_stage
- from **codeintel_rev.telemetry.prom** import record_stage_latency

## Definitions

- class: `_NullSpan` (line 22)
- class: `_SpanContext` (line 94)
- class: `_NoopTracer` (line 101)
- class: `_SpanKindEnum` (line 139)
- class: `_StatusCodeEnum` (line 146)
- class: `_StatusStub` (line 150)
- variable: `trace` (line 153)
- variable: `Span` (line 154)
- variable: `SpanKind` (line 155)
- variable: `Status` (line 156)
- variable: `StatusCode` (line 157)
- variable: `SpanType` (line 165)
- variable: `SpanKindType` (line 166)
- variable: `StatusType` (line 167)
- variable: `StatusCodeType` (line 168)
- variable: `LOGGER` (line 175)
- variable: `F` (line 177)
- variable: `TRACER` (line 187)
- function: `_emit_checkpoint` (line 190)
- function: `_set_span_attributes` (line 238)
- function: `_span_scope` (line 273)
- function: `_record_exception` (line 340)
- function: `span_context` (line 374)
- function: `trace_span` (line 462)
- function: `trace_step` (line 614)
- function: `emit_event` (line 662)
- function: `_build_step_payload` (line 806)
- function: `_with_duration` (line 822)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 5
- **cycle_group**: 55

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

emit_event, span_context, trace_span, trace_step

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

- score: 2.62

## Side Effects

- none detected

## Complexity

- branches: 35
- cyclomatic: 36
- loc: 829

## Doc Coverage

- `_NullSpan` (class): summary=yes, examples=no — Minimal span stub used when OpenTelemetry is unavailable.
- `_SpanContext` (class): summary=no, examples=no
- `_NoopTracer` (class): summary=no, examples=no
- `_SpanKindEnum` (class): summary=no, examples=no
- `_StatusCodeEnum` (class): summary=no, examples=no
- `_StatusStub` (class): summary=no, examples=no
- `_emit_checkpoint` (function): summary=yes, params=ok, examples=no — Emit a checkpoint event for telemetry reporting.
- `_set_span_attributes` (function): summary=yes, params=ok, examples=no — Set attributes on an OpenTelemetry span from a mapping.
- `_span_scope` (function): summary=yes, params=ok, examples=no — Create a context manager for OpenTelemetry span and timeline step coordination.
- `_record_exception` (function): summary=yes, params=ok, examples=no — Record an exception on an OpenTelemetry span and mark it as an error.

## Tags

low-coverage, public-api
