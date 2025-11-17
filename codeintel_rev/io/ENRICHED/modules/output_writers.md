# enrich/output_writers.py

## Docstring

```
Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **collections.abc** import Callable, Iterable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any
- from **(absolute)** import orjson
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.dataset
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow

## Definitions

- variable: `orjson` (line 17)
- variable: `pa` (line 24)
- variable: `ds` (line 25)
- variable: `pq` (line 26)
- variable: `PaTable` (line 31)
- variable: `PaTable` (line 33)
- variable: `RowMapping` (line 35)
- function: `_dump_json` (line 54)
- function: `_dump_jsonl_bytes` (line 77)
- function: `_resolve_dictionary_fields` (line 106)
- function: `write_json` (line 132)
- class: `WriterEnvConfig` (line 140)
- function: `override_writer_env` (line 150)
- function: `_resolve_env` (line 162)
- function: `write_jsonl` (line 169)
- function: `write_parquet` (line 197)
- function: `write_parquet_dataset` (line 210)
- function: `_write_dataset_table` (line 261)
- function: `_append_section` (line 301)
- function: `_format_imports` (line 309)
- function: `_format_definitions` (line 328)
- function: `_format_graph_metrics` (line 344)
- function: `_format_ownership` (line 353)
- function: `_format_usage` (line 375)
- function: `_format_exports` (line 386)
- function: `_format_exports_resolved` (line 394)
- function: `_format_reexports` (line 404)
- function: `_format_doc_metrics` (line 418)
- function: `_format_typedness` (line 433)
- function: `_format_side_effects` (line 452)
- function: `_format_raises` (line 462)
- function: `_format_complexity` (line 471)
- function: `_format_doc_items` (line 483)
- function: `_format_coverage` (line 510)
- function: `_format_config_refs` (line 521)
- function: `_format_hotspot` (line 528)
- function: `write_markdown_module` (line 535)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 61

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 13
- recent churn 90: 13

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown).
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

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.69

## Side Effects

- filesystem

## Complexity

- branches: 114
- cyclomatic: 115
- loc: 570

## Doc Coverage

- `_dump_json` (function): summary=yes, params=ok, examples=no — Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.
- `_dump_jsonl_bytes` (function): summary=yes, params=ok, examples=no — Serialize JSON rows for JSONL outputs with deterministic ordering.
- `_resolve_dictionary_fields` (function): summary=yes, params=ok, examples=no — Return dictionary-encoded columns present in ``table``.
- `write_json` (function): summary=yes, params=mismatch, examples=no — Write an object as pretty-printed JSON.
- `WriterEnvConfig` (class): summary=yes, examples=no — Configuration for resolving writer environment variables.
- `override_writer_env` (function): summary=yes, params=mismatch, examples=no — Temporarily override the environment resolver for JSONL writers.
- `_resolve_env` (function): summary=no, examples=no
- `write_jsonl` (function): summary=yes, params=mismatch, examples=no — Write newline-delimited JSON records.
- `write_parquet` (function): summary=yes, params=mismatch, examples=no — Persist ``rows`` to Parquet, falling back to JSONL when PyArrow is missing.
- `write_parquet_dataset` (function): summary=yes, params=ok, examples=no — Write records to a partitioned Parquet dataset directory.

## Tags

low-coverage
