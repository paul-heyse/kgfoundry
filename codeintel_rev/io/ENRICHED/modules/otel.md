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
- class: `_MetricsAPI` (line 37)
- class: `_TracerProviderInstance` (line 57)
- class: `_TracerProviderFactory` (line 79)
- class: `_Factory` (line 83)
- class: `_ResourceFactory` (line 87)
- function: `_optional_import` (line 117)
- function: `_import_attr` (line 124)
- variable: `otel_metrics` (line 131)
- variable: `otel_trace` (line 132)
- variable: `OTLPMetricExporter` (line 133)
- variable: `OTLPSpanExporter` (line 137)
- variable: `MeterProvider` (line 141)
- variable: `PeriodicExportingMetricReader` (line 145)
- variable: `ConsoleMetricExporter` (line 149)
- variable: `Resource` (line 153)
- variable: `TracerProvider` (line 157)
- variable: `BatchSpanProcessor` (line 161)
- variable: `ConsoleSpanExporter` (line 165)
- class: `OtelInstallResult` (line 175)
- class: `_TelemetryDeps` (line 183)
- function: `_resolve_factories` (line 194)
- function: `_env_flag` (line 220)
- function: `_service_version` (line 227)
- function: `build_resource` (line 236)
- function: `_build_span_exporter` (line 296)
- function: `_build_metric_exporter` (line 302)
- function: `install_otel` (line 308)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 53

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

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

- score: 2.10

## Side Effects

- filesystem

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 384

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
