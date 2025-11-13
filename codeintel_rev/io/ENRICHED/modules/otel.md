# telemetry/otel.py

## Docstring

```
OpenTelemetry bootstrap helpers for CodeIntel.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **dataclasses** import dataclass
- from **importlib** import metadata
- from **types** import ModuleType
- from **typing** import Protocol, cast
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 14)
- class: `_TraceAPI` (line 17)
- class: `_MetricsAPI` (line 21)
- class: `_TracerProviderInstance` (line 25)
- class: `_TracerProviderFactory` (line 29)
- class: `_Factory` (line 33)
- class: `_ResourceFactory` (line 37)
- function: `_optional_import` (line 42)
- function: `_import_attr` (line 49)
- variable: `otel_metrics` (line 56)
- variable: `otel_trace` (line 57)
- variable: `OTLPMetricExporter` (line 58)
- variable: `OTLPSpanExporter` (line 62)
- variable: `MeterProvider` (line 66)
- variable: `PeriodicExportingMetricReader` (line 70)
- variable: `ConsoleMetricExporter` (line 74)
- variable: `Resource` (line 78)
- variable: `TracerProvider` (line 82)
- variable: `BatchSpanProcessor` (line 86)
- variable: `ConsoleSpanExporter` (line 90)
- class: `OtelInstallResult` (line 100)
- class: `_TelemetryDeps` (line 108)
- function: `_resolve_factories` (line 119)
- function: `_env_flag` (line 145)
- function: `_service_version` (line 152)
- function: `build_resource` (line 161)
- function: `_build_span_exporter` (line 221)
- function: `_build_metric_exporter` (line 227)
- function: `install_otel` (line 233)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 80

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

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

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 309

## Doc Coverage

- `_TraceAPI` (class): summary=no, examples=no
- `_MetricsAPI` (class): summary=no, examples=no
- `_TracerProviderInstance` (class): summary=no, examples=no
- `_TracerProviderFactory` (class): summary=no, examples=no
- `_Factory` (class): summary=no, examples=no
- `_ResourceFactory` (class): summary=no, examples=no
- `_optional_import` (function): summary=no, examples=no
- `_import_attr` (function): summary=no, examples=no
- `OtelInstallResult` (class): summary=yes, examples=no — Summary describing which signal providers were installed.
- `_TelemetryDeps` (class): summary=no, examples=no

## Tags

low-coverage
