# enrich/output_writers.py

## Docstring

```
Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **collections.abc** import Iterable, Mapping, Sequence
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any
- from **(absolute)** import orjson
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.dataset
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow

## Definitions

- variable: `orjson` (line 15)
- variable: `pa` (line 22)
- variable: `ds` (line 23)
- variable: `pq` (line 24)
- variable: `PaTable` (line 29)
- variable: `PaTable` (line 31)
- variable: `RowMapping` (line 33)
- function: `_dump_json` (line 52)
- function: `_dump_jsonl_bytes` (line 75)
- function: `_resolve_dictionary_fields` (line 104)
- function: `write_json` (line 130)
- function: `write_jsonl` (line 137)
- function: `write_parquet` (line 158)
- function: `write_parquet_dataset` (line 171)
- function: `_write_dataset_table` (line 222)
- function: `_append_section` (line 264)
- function: `_format_imports` (line 272)
- function: `_format_definitions` (line 291)
- function: `_format_graph_metrics` (line 307)
- function: `_format_ownership` (line 316)
- function: `_format_usage` (line 338)
- function: `_format_exports` (line 349)
- function: `_format_exports_resolved` (line 357)
- function: `_format_reexports` (line 367)
- function: `_format_doc_metrics` (line 381)
- function: `_format_typedness` (line 396)
- function: `_format_side_effects` (line 415)
- function: `_format_raises` (line 425)
- function: `_format_complexity` (line 434)
- function: `_format_doc_items` (line 446)
- function: `_format_coverage` (line 473)
- function: `_format_config_refs` (line 484)
- function: `_format_hotspot` (line 491)
- function: `write_markdown_module` (line 498)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 97

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

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

- score: 2.68

## Side Effects

- filesystem

## Complexity

- branches: 111
- cyclomatic: 112
- loc: 533

## Doc Coverage

- `_dump_json` (function): summary=yes, params=ok, examples=no — Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.
- `_dump_jsonl_bytes` (function): summary=yes, params=ok, examples=no — Serialize JSON rows for JSONL outputs with deterministic ordering.
- `_resolve_dictionary_fields` (function): summary=yes, params=ok, examples=no — Return dictionary-encoded columns present in ``table``.
- `write_json` (function): summary=yes, params=mismatch, examples=no — Write an object as pretty-printed JSON.
- `write_jsonl` (function): summary=yes, params=mismatch, examples=no — Write newline-delimited JSON records.
- `write_parquet` (function): summary=yes, params=mismatch, examples=no — Persist ``rows`` to Parquet, falling back to JSONL when PyArrow is missing.
- `write_parquet_dataset` (function): summary=yes, params=ok, examples=no — Write records to a partitioned Parquet dataset directory.
- `_write_dataset_table` (function): summary=yes, params=mismatch, examples=no — Write ``table`` to Parquet using dataset writer settings.
- `_append_section` (function): summary=no, examples=no
- `_format_imports` (function): summary=no, examples=no

## Tags

low-coverage
