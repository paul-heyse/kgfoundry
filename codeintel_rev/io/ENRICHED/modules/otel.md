# observability/otel.py

## Docstring

```
Optional OpenTelemetry bootstrap helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **collections.abc** import Mapping, Sequence
- from **contextlib** import AbstractContextManager, suppress
- from **dataclasses** import dataclass
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Any, Protocol, cast
- from **codeintel_rev.observability.logs** import init_otel_logging
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import start_span
- from **opentelemetry.sdk.resources** import Resource
- from **codeintel_rev.observability.flight_recorder** import install_flight_recorder
- from **codeintel_rev.observability.metrics** import install_metrics_provider

## Definitions

- variable: `LOGGER` (line 27)
- variable: `SpanAttribute` (line 29)
- class: `_TelemetryState` (line 32)
- class: `SupportsState` (line 55)
- class: `_TraceHandles` (line 62)
- function: `_env_flag` (line 80)
- function: `_sanitize_span_attrs` (line 110)
- function: `_coerce_span_value` (line 119)
- function: `_should_enable` (line 133)
- function: `_optional_import` (line 139)
- function: `_load_trace_modules` (line 146)
- function: `_parse_sampler_spec` (line 173)
- function: `_build_sampler` (line 186)
- function: `_build_resource` (line 215)
- function: `_merge_detected_resources` (line 250)
- function: `_build_provider` (line 293)
- function: `telemetry_enabled` (line 321)
- function: `_initialize_tracing_state` (line 332)
- function: `_initialize_metrics_provider` (line 350)
- function: `_initialize_flight_recorder` (line 377)
- function: `init_telemetry` (line 393)
- function: `init_otel` (line 459)
- function: `init_all_telemetry` (line 482)
- function: `as_span` (line 506)
- function: `record_span_event` (line 534)
- function: `_current_span` (line 558)
- function: `set_current_span_attrs` (line 571)
- function: `_current_span_context` (line 587)
- function: `current_trace_id` (line 600)
- function: `current_span_id` (line 616)
- function: `_install_logging_instrumentation` (line 632)
- function: `instrument_fastapi` (line 646)
- function: `instrument_httpx` (line 661)

## Graph Metrics

- **fan_in**: 23
- **fan_out**: 4
- **cycle_group**: 9

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 13
- recent churn 90: 13

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

as_span, current_span_id, current_trace_id, init_all_telemetry, init_otel, init_telemetry, instrument_fastapi, instrument_httpx, record_span_event, set_current_span_attrs, telemetry_enabled

## Doc Health

- **summary**: Optional OpenTelemetry bootstrap helpers.
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

- score: 3.27

## Side Effects

- filesystem

## Complexity

- branches: 101
- cyclomatic: 102
- loc: 689

## Doc Coverage

- `_TelemetryState` (class): summary=yes, examples=no — Mutable telemetry state shared across module functions.
- `SupportsState` (class): summary=yes, examples=no — Protocol describing FastAPI-style objects exposing ``state``.
- `_TraceHandles` (class): summary=no, examples=no
- `_env_flag` (function): summary=yes, params=ok, examples=no — Check if an environment variable is set to a truthy value.
- `_sanitize_span_attrs` (function): summary=no, examples=no
- `_coerce_span_value` (function): summary=no, examples=no
- `_should_enable` (function): summary=no, examples=no
- `_optional_import` (function): summary=no, examples=no
- `_load_trace_modules` (function): summary=no, examples=no
- `_parse_sampler_spec` (function): summary=no, examples=no

## Tags

low-coverage, public-api, reexport-hub
