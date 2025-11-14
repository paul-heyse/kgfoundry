# enrich/type_integration.py

## Docstring

```
Helpers for collecting Pyright/Pyrefly error summaries.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import json
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **pathlib** import Path

## Definitions

- class: `TypeFileSummary` (line 14)
- class: `TypeSummary` (line 23)
- function: `_run_command_async` (line 29)
- function: `_try_run` (line 74)
- function: `collect_pyright` (line 104)
- function: `collect_pyrefly` (line 143)
- function: `_parse_pyrefly_jsonl` (line 174)
- function: `_parse_pyrefly_json` (line 183)
- function: `_apply_pyrefly_record` (line 190)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 18

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Helpers for collecting Pyright/Pyrefly error summaries.
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

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 1.79

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 23
- cyclomatic: 24
- loc: 201

## Doc Coverage

- `TypeFileSummary` (class): summary=yes, examples=no — Aggregated type-checker results for a single file.
- `TypeSummary` (class): summary=yes, examples=no — Mapping of file path → :class:`TypeFileSummary`.
- `_run_command_async` (function): summary=yes, params=ok, examples=no — Run a command asynchronously and capture stdout/stderr.
- `_try_run` (function): summary=yes, params=ok, examples=no — Run the asynchronous helper in a synchronous context.
- `collect_pyright` (function): summary=yes, params=ok, examples=no — Run Pyright (or BasedPyright) and summarize diagnostics.
- `collect_pyrefly` (function): summary=yes, params=ok, examples=no — Parse a Pyrefly JSON/JSONL report produced by CI.
- `_parse_pyrefly_jsonl` (function): summary=yes, params=mismatch, examples=no — Apply Pyrefly records from a JSONL file to the summary.
- `_parse_pyrefly_json` (function): summary=yes, params=mismatch, examples=no — Apply Pyrefly records from a JSON file to the summary.
- `_apply_pyrefly_record` (function): summary=yes, params=mismatch, examples=no — Merge a single Pyrefly record into the summary.

## Tags

low-coverage
