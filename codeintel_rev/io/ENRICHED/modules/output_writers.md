# enrich/output_writers.py

## Docstring

```
Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **pathlib** import Path
- from **(absolute)** import orjson
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `orjson` (line 13)
- variable: `pa` (line 19)
- variable: `pq` (line 20)
- function: `_dump_json` (line 23)
- function: `write_json` (line 46)
- function: `write_jsonl` (line 53)
- function: `write_parquet` (line 63)
- function: `_append_section` (line 76)
- function: `_format_imports` (line 84)
- function: `_format_definitions` (line 103)
- function: `_format_graph_metrics` (line 119)
- function: `_format_ownership` (line 128)
- function: `_format_usage` (line 150)
- function: `_format_exports` (line 161)
- function: `_format_exports_resolved` (line 169)
- function: `_format_reexports` (line 179)
- function: `_format_doc_metrics` (line 193)
- function: `_format_typedness` (line 208)
- function: `_format_side_effects` (line 227)
- function: `_format_raises` (line 237)
- function: `_format_complexity` (line 246)
- function: `_format_doc_items` (line 258)
- function: `_format_coverage` (line 285)
- function: `_format_config_refs` (line 296)
- function: `_format_hotspot` (line 303)
- function: `write_markdown_module` (line 310)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 0
- **cycle_group**: 10

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

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

- score: 2.55

## Side Effects

- filesystem

## Complexity

- branches: 90
- cyclomatic: 91
- loc: 345

## Doc Coverage

- `_dump_json` (function): summary=yes, params=ok, examples=no — Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.
- `write_json` (function): summary=yes, params=mismatch, examples=no — Write an object as pretty-printed JSON.
- `write_jsonl` (function): summary=yes, params=mismatch, examples=no — Write newline-delimited JSON records.
- `write_parquet` (function): summary=yes, params=mismatch, examples=no — Persist ``rows`` to Parquet, falling back to JSONL when PyArrow is missing.
- `_append_section` (function): summary=no, examples=no
- `_format_imports` (function): summary=no, examples=no
- `_format_definitions` (function): summary=no, examples=no
- `_format_graph_metrics` (function): summary=no, examples=no
- `_format_ownership` (function): summary=no, examples=no
- `_format_usage` (function): summary=no, examples=no

## Tags

low-coverage
