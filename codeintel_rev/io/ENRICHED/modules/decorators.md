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
- from **time** import perf_counter
- from **typing** import TypeVar, cast
- from **codeintel_rev.metrics.registry** import MCP_STAGE_LATENCY_SECONDS
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.telemetry** import steps
- from **codeintel_rev.telemetry.context** import attach_context_attrs, set_request_stage
- from **codeintel_rev.telemetry.otel_shim** import SpanKind, SpanKindType, SpanType, Status, StatusCode, StatusCodeType, StatusFactory, trace_api

## Definitions

- variable: `LOGGER` (line 29)
- variable: `F` (line 31)
- function: `_record_stage_latency` (line 34)
- variable: `TRACER` (line 50)
- function: `_emit_checkpoint` (line 53)
- function: `_set_span_attributes` (line 101)
- function: `_span_scope` (line 136)
- function: `_record_exception` (line 203)
- function: `span_context` (line 237)
- function: `trace_span` (line 325)
- function: `trace_step` (line 477)
- function: `emit_event` (line 525)
- function: `_build_step_payload` (line 669)
- function: `_with_duration` (line 685)

## Graph Metrics

- **fan_in**: 10
- **fan_out**: 6
- **cycle_group**: 26

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

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

- score: 2.75

## Side Effects

- none detected

## Complexity

- branches: 34
- cyclomatic: 35
- loc: 692

## Doc Coverage

- `_record_stage_latency` (function): summary=yes, params=mismatch, examples=no — Record latency for a retrieval stage.
- `_emit_checkpoint` (function): summary=yes, params=ok, examples=no — Emit a checkpoint event for telemetry reporting.
- `_set_span_attributes` (function): summary=yes, params=ok, examples=no — Set attributes on an OpenTelemetry span from a mapping.
- `_span_scope` (function): summary=yes, params=ok, examples=no — Create a context manager for OpenTelemetry span and timeline step coordination.
- `_record_exception` (function): summary=yes, params=ok, examples=no — Record an exception on an OpenTelemetry span and mark it as an error.
- `span_context` (function): summary=yes, params=ok, examples=no — Create a span/timeline scope for the wrapped block.
- `trace_span` (function): summary=yes, params=ok, examples=no — Wrap callable execution in an OpenTelemetry span + timeline step.
- `trace_step` (function): summary=yes, params=ok, examples=no — Specialized decorator that records checkpoints for pipeline stages.
- `emit_event` (function): summary=yes, params=ok, examples=no — Emit a :class:`StepEvent` reflecting the wrapped callable's outcome.
- `_build_step_payload` (function): summary=no, examples=no

## Tags

low-coverage, public-api
