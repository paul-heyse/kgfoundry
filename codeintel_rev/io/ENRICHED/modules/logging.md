# telemetry/logging.py

## Docstring

```
Structured logging bridge + optional OTLP exporter.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import logging
- from **codeintel_rev.observability.logs** import init_otel_logging
- from **kgfoundry_common.logging** import setup_logging

## Definitions

- variable: `LOGGER` (line 10)
- function: `install_structured_logging` (line 14)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 57

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

- score: 1.40

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 27

## Doc Coverage

- `install_structured_logging` (function): summary=yes, params=mismatch, examples=no — Install JSON logging and delegate OpenTelemetry export to observability stack.

## Tags

low-coverage
