# telemetry/otel.py

## Docstring

```
OpenTelemetry bootstrap helpers for CodeIntel.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **dataclasses** import dataclass
- from **importlib** import metadata
- from **typing** import Any
- from **opentelemetry** import metrics
- from **opentelemetry** import trace
- from **opentelemetry.exporter.otlp.proto.http.metric_exporter** import OTLPMetricExporter
- from **opentelemetry.exporter.otlp.proto.http.trace_exporter** import OTLPSpanExporter
- from **opentelemetry.sdk.metrics** import MeterProvider
- from **opentelemetry.sdk.metrics.export** import ConsoleMetricExporter, PeriodicExportingMetricReader
- from **opentelemetry.sdk.resources** import Resource
- from **opentelemetry.sdk.trace** import TracerProvider
- from **opentelemetry.sdk.trace.export** import BatchSpanProcessor, ConsoleSpanExporter
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `otel_metrics` (line 27)
- variable: `otel_trace` (line 28)
- variable: `OTLPMetricExporter` (line 29)
- variable: `OTLPSpanExporter` (line 30)
- variable: `MeterProvider` (line 31)
- variable: `PeriodicExportingMetricReader` (line 32)
- variable: `ConsoleMetricExporter` (line 33)
- variable: `BatchSpanProcessor` (line 34)
- variable: `ConsoleSpanExporter` (line 35)
- variable: `Resource` (line 36)
- variable: `TracerProvider` (line 37)
- variable: `LOGGER` (line 41)
- function: `_env_flag` (line 44)
- function: `_service_version` (line 74)
- function: `build_resource` (line 90)
- class: `OtelInstallResult` (line 153)
- function: `_build_span_exporter` (line 160)
- function: `_build_metric_exporter` (line 190)
- function: `install_otel` (line 220)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 79

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: OpenTelemetry bootstrap helpers for CodeIntel.
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

- score: 2.17

## Side Effects

- filesystem

## Complexity

- branches: 24
- cyclomatic: 25
- loc: 308

## Doc Coverage

- `_env_flag` (function): summary=yes, params=ok, examples=no — Return environment flag value.
- `_service_version` (function): summary=yes, params=ok, examples=no — Return package version for resource attributes.
- `build_resource` (function): summary=yes, params=ok, examples=no — Build an OpenTelemetry Resource describing this process.
- `OtelInstallResult` (class): summary=yes, examples=no — Summary describing which signal providers were installed.
- `_build_span_exporter` (function): summary=yes, params=ok, examples=no — Return an OTLP span exporter when configured.
- `_build_metric_exporter` (function): summary=yes, params=ok, examples=no — Return an OTLP metric exporter when configured.
- `install_otel` (function): summary=yes, params=ok, examples=no — Install tracer/meter providers with console fallbacks.

## Tags

low-coverage
