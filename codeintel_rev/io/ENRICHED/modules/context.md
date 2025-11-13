# telemetry/context.py

## Docstring

```
Context variable helpers for telemetry metadata.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **collections.abc** import Iterator, Mapping
- from **contextlib** import contextmanager
- from **typing** import Any
- from **codeintel_rev.runtime.request_context** import capability_stamp_var
- from **codeintel_rev.runtime.request_context** import session_id_var
- from **kgfoundry_common.logging** import set_correlation_id

## Definitions

- variable: `session_id_var` (line 18)
- variable: `capability_stamp_var` (line 19)
- variable: `run_id_var` (line 20)
- variable: `request_tool_var` (line 24)
- variable: `stage_var` (line 28)
- function: `current_session` (line 48)
- function: `current_run_id` (line 59)
- function: `_set_run_id` (line 70)
- function: `set_request_stage` (line 76)
- function: `current_stage` (line 92)
- function: `telemetry_context` (line 104)
- function: `attach_context_attrs` (line 126)
- function: `telemetry_metadata` (line 158)

## Graph Metrics

- **fan_in**: 8
- **fan_out**: 2
- **cycle_group**: 47

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

attach_context_attrs, capability_stamp_var, current_run_id, current_session, current_stage, request_tool_var, run_id_var, session_id_var, set_request_stage, telemetry_context, telemetry_metadata

## Doc Health

- **summary**: Context variable helpers for telemetry metadata.
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

- score: 2.30

## Side Effects

- none detected

## Complexity

- branches: 12
- cyclomatic: 13
- loc: 176

## Doc Coverage

- `current_session` (function): summary=yes, params=ok, examples=no — Return the session identifier stored in context.
- `current_run_id` (function): summary=yes, params=ok, examples=no — Return the active run identifier (alias of the current trace ID).
- `_set_run_id` (function): summary=no, examples=no
- `set_request_stage` (function): summary=yes, params=ok, examples=no — Bind the current pipeline stage to the context.
- `current_stage` (function): summary=yes, params=ok, examples=no — Return the stage currently executing within the request.
- `telemetry_context` (function): summary=yes, params=mismatch, examples=no — Bind telemetry identifiers to the current context.
- `attach_context_attrs` (function): summary=yes, params=ok, examples=no — Return attributes merged with current telemetry identifiers.
- `telemetry_metadata` (function): summary=yes, params=ok, examples=no — Return telemetry metadata (session/run IDs) for response envelopes.

## Tags

low-coverage, public-api, reexport-hub
