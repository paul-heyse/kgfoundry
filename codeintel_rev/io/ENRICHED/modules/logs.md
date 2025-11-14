# observability/logs.py

## Docstring

```
OpenTelemetry logging bootstrap helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import logging
- from **(absolute)** import os
- from **collections.abc** import Iterable
- from **kgfoundry_common.logging** import get_logger
- from **opentelemetry._logs** import set_logger_provider
- from **opentelemetry.sdk._logs** import LoggerProvider, LoggingHandler
- from **opentelemetry.sdk._logs.export** import BatchLogRecordProcessor
- from **opentelemetry.sdk.resources** import Resource
- from **opentelemetry.exporter.otlp.proto.http.log_exporter** import OTLPLogExporter

## Definitions

- variable: `set_logger_provider` (line 18)
- variable: `LoggerProvider` (line 19)
- variable: `LoggingHandler` (line 20)
- variable: `BatchLogRecordProcessor` (line 21)
- variable: `Resource` (line 22)
- variable: `OTLPLogExporter` (line 29)
- variable: `LOGGER` (line 32)
- function: `_should_enable` (line 38)
- function: `_instrument_stdlib_logging` (line 47)
- function: `init_otel_logging` (line 66)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 8

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

init_otel_logging

## Doc Health

- **summary**: OpenTelemetry logging bootstrap helpers.
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

- score: 1.90

## Side Effects

- filesystem

## Complexity

- branches: 19
- cyclomatic: 20
- loc: 115

## Doc Coverage

- `_should_enable` (function): summary=no, examples=no
- `_instrument_stdlib_logging` (function): summary=yes, params=ok, examples=no — Enable OpenTelemetry's stdlib logging bridge when the package is installed.
- `init_otel_logging` (function): summary=yes, params=mismatch, examples=no — Bridge stdlib logging into OpenTelemetry logs when available.

## Tags

low-coverage, public-api
