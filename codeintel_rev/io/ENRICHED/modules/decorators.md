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
- from **codeintel_rev.telemetry.context** import attach_context_attrs, set_request_stage
- from **codeintel_rev.telemetry.prom** import record_stage_latency

## Definitions

- class: `_NullSpan` (line 21)
- class: `_SpanContext` (line 93)
- class: `_NoopTracer` (line 100)
- class: `_SpanKindEnum` (line 138)
- class: `_StatusCodeEnum` (line 145)
- class: `_StatusStub` (line 149)
- variable: `trace` (line 152)
- variable: `Span` (line 153)
- variable: `SpanKind` (line 154)
- variable: `Status` (line 155)
- variable: `StatusCode` (line 156)
- variable: `SpanType` (line 164)
- variable: `SpanKindType` (line 165)
- variable: `StatusType` (line 166)
- variable: `StatusCodeType` (line 167)
- variable: `F` (line 173)
- variable: `TRACER` (line 183)
- function: `_emit_checkpoint` (line 186)
- function: `_set_span_attributes` (line 233)
- function: `_span_scope` (line 268)
- function: `_record_exception` (line 335)
- function: `span_context` (line 369)
- function: `trace_span` (line 457)
- function: `trace_step` (line 609)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 4
- **cycle_group**: 46

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

- score: 2.54

## Side Effects

- none detected

## Complexity

- branches: 29
- cyclomatic: 30
- loc: 658

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
