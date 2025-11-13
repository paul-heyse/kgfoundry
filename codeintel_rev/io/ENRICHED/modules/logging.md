# telemetry/logging.py

## Docstring

```
Structured logging bridge + optional OTLP exporter.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import logging
- from **(absolute)** import os
- from **codeintel_rev.telemetry.otel** import _env_flag, build_resource
- from **kgfoundry_common.logging** import setup_logging
- from **opentelemetry.exporter.otlp.proto.http._log_exporter** import OTLPLogExporter
- from **opentelemetry.sdk._logs** import LoggerProvider, LoggingHandler
- from **opentelemetry.sdk._logs.export** import BatchLogRecordProcessor

## Definitions

- variable: `OTLPLogExporter` (line 16)
- variable: `LoggerProvider` (line 17)
- variable: `LoggingHandler` (line 18)
- variable: `BatchLogRecordProcessor` (line 19)
- variable: `LOGGER` (line 21)
- function: `install_structured_logging` (line 25)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 80

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

- **summary**: Structured logging bridge + optional OTLP exporter.
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

- score: 1.69

## Side Effects

- filesystem

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 58

## Doc Coverage

- `install_structured_logging` (function): summary=yes, params=mismatch, examples=no — Install JSON logging and optional OTLP log export.

## Tags

low-coverage
