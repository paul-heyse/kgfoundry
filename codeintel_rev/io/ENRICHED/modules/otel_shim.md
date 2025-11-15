# telemetry/otel_shim.py

## Docstring

```
Typed OpenTelemetry shims with graceful fallbacks.

This module centralizes our optional OpenTelemetry imports so that other modules
can depend on a stable interface regardless of whether Otel is installed. When
the real SDK is present we simply re-export its classes. Otherwise we provide
lightweight stub implementations that satisfy the type checker and preserve the
call contracts used throughout the codebase.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping
- from **contextlib** import AbstractContextManager
- from **dataclasses** import dataclass, field
- from **typing** import Protocol, cast, runtime_checkable
- from **importlib** import import_module

## Definitions

- class: `SpanContextProtocol` (line 20)
- class: `SpanProtocol` (line 35)
- class: `TracerProtocol` (line 68)
- class: `TraceAPILike` (line 81)
- class: `SpanKindProtocol` (line 99)
- class: `StatusProtocol` (line 109)
- class: `StatusFactory` (line 115)
- class: `StatusCodeProtocol` (line 122)
- class: `_SpanContextStub` (line 130)
- class: `_NullSpan` (line 138)
- class: `_NullSpanContextManager` (line 221)
- class: `_NoopTracer` (line 253)
- class: `_TraceStub` (line 286)
- class: `_SpanKindStub` (line 340)
- class: `_StatusStub` (line 351)
- class: `_StatusCodeStub` (line 357)
- variable: `trace_api` (line 368)
- variable: `trace_api` (line 383)
- variable: `SpanType` (line 389)
- variable: `SpanKindType` (line 390)
- variable: `StatusType` (line 391)
- variable: `StatusCodeType` (line 392)
- variable: `Span` (line 394)
- variable: `SpanKind` (line 395)
- variable: `Status` (line 396)
- variable: `StatusCode` (line 397)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 13

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

Span, SpanKind, SpanKindType, SpanProtocol, SpanType, Status, StatusCode, StatusCodeType, StatusType, TraceAPILike, trace_api

## Doc Health

- **summary**: Typed OpenTelemetry shims with graceful fallbacks.
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

- score: 1.69

## Side Effects

- none detected

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 413

## Doc Coverage

- `SpanContextProtocol` (class): summary=yes, examples=no — Subset of :class:`opentelemetry.trace.SpanContext` that we consume.
- `SpanProtocol` (class): summary=yes, examples=no — Methods we rely on for span manipulation.
- `TracerProtocol` (class): summary=yes, examples=no — Tracer hook used by our decorators and telemetry sinks.
- `TraceAPILike` (class): summary=yes, examples=no — Surface area from :mod:`opentelemetry.trace` that we consume.
- `SpanKindProtocol` (class): summary=yes, examples=no — Interface of ``SpanKind`` enums we depend on.
- `StatusProtocol` (class): summary=yes, examples=no — Interface of ``Status`` values.
- `StatusFactory` (class): summary=yes, examples=no — Constructor protocol for ``Status`` implementations.
- `StatusCodeProtocol` (class): summary=yes, examples=no — Interface of ``StatusCode`` enums.
- `_SpanContextStub` (class): summary=yes, examples=no — Minimal span context stub used when OpenTelemetry is unavailable.
- `_NullSpan` (class): summary=yes, examples=no — No-op span implementation.

## Tags

low-coverage, public-api, reexport-hub
