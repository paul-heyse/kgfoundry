# observability/execution_ledger.py

## Docstring

```
Deterministic execution ledger aligned with OpenTelemetry traces.

This module captures per-request execution data that can be replayed as a
"run report" describing exactly which stages executed, how long they took,
and why a request stopped. The public API mirrors the spec described in
``codeintel_rev/patches/Telemetry_Execution_Ledger.md``: call :func:`begin_run`
from MCP adapters, wrap stage handlers with :func:`step`, emit ad-hoc events
via :func:`record`, and finish with :func:`end_run` to persist the run into the
in-process ring buffer (and optional JSONL sink).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import textwrap
- from **(absolute)** import time
- from **(absolute)** import uuid
- from **collections** import OrderedDict
- from **collections.abc** import Iterable, Mapping, Sequence
- from **contextlib** import ContextDecorator
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **functools** import wraps
- from **pathlib** import Path
- from **threading** import RLock
- from **types** import TracebackType
- from **typing** import Any, Self, TypedDict
- from **(absolute)** import msgspec
- from **codeintel_rev.observability.otel** import current_span_id, current_trace_id, record_span_event
- from **codeintel_rev.observability.semantic_conventions** import Attrs, as_kv
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 41)
- variable: `DEFAULT_STAGE_SEQUENCE` (line 43)
- function: `_env_flag` (line 64)
- function: `_env_int` (line 71)
- class: `LedgerSettings` (line 84)
- class: `LedgerEntry` (line 93)
- class: `LedgerRun` (line 111)
- class: `LedgerReportEntry` (line 129)
- class: `LedgerReportPayload` (line 141)
- class: `ExecutionLedgerStore` (line 165)
- class: `_ActiveRun` (line 253)
- function: `_sanitize_request` (line 466)
- function: `_normalize_attrs` (line 499)
- function: `_infer_stop_reason` (line 521)
- function: `_stage_durations` (line 564)
- function: `_collect_warnings` (line 588)
- function: `_load_settings` (line 613)
- variable: `SETTINGS` (line 633)
- variable: `STORE` (line 634)
- function: `current_run` (line 640)
- function: `begin_run` (line 653)
- function: `end_run` (line 729)
- class: `LedgerStep` (line 782)
- function: `step` (line 935)
- function: `record` (line 968)
- function: `get_run` (line 1039)
- function: `build_run_report` (line 1056)
- function: `to_json` (line 1076)
- function: `to_markdown` (line 1104)
- function: `_serialize_run` (line 1121)
- function: `_build_report_payload` (line 1156)
- function: `_extract_envelope_summary` (line 1178)
- function: `report_to_markdown` (line 1185)

## Graph Metrics

- **fan_in**: 12
- **fan_out**: 3
- **cycle_group**: 14

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

DEFAULT_STAGE_SEQUENCE, ExecutionLedgerStore, LedgerEntry, LedgerReportEntry, LedgerReportPayload, LedgerRun, LedgerSettings, LedgerStep, begin_run, build_run_report, current_run, end_run, get_run, record, report_to_markdown, step, to_json, to_markdown

## Doc Health

- **summary**: Deterministic execution ledger aligned with OpenTelemetry traces.
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

- score: 3.01

## Side Effects

- filesystem

## Complexity

- branches: 90
- cyclomatic: 91
- loc: 1246

## Doc Coverage

- `_env_flag` (function): summary=no, examples=no
- `_env_int` (function): summary=no, examples=no
- `LedgerSettings` (class): summary=yes, examples=no — Runtime configuration for the execution ledger.
- `LedgerEntry` (class): summary=yes, examples=no — Structured record describing a single operation within a run.
- `LedgerRun` (class): summary=yes, examples=no — Complete ledger snapshot for a single MCP request.
- `LedgerReportEntry` (class): summary=yes, examples=no — Structured dictionary representing a single ledger entry.
- `LedgerReportPayload` (class): summary=yes, examples=no — Serialized ledger run enriched with derived diagnostics.
- `ExecutionLedgerStore` (class): summary=yes, examples=no — Append-only in-process store with optional JSONL persistence.
- `_ActiveRun` (class): summary=yes, examples=no — Mutable run state bound to the current request context.
- `_sanitize_request` (function): summary=yes, params=ok, examples=no — Sanitize request payload by redacting sensitive fields.

## Tags

low-coverage, public-api, reexport-hub
