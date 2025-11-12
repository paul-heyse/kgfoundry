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
- function: `_dump_json` (line 16)
- function: `write_json` (line 39)
- function: `write_jsonl` (line 46)
- function: `write_parquet` (line 56)
- function: `_append_section` (line 72)
- function: `_format_imports` (line 80)
- function: `_format_definitions` (line 99)
- function: `_format_graph_metrics` (line 115)
- function: `_format_ownership` (line 124)
- function: `_format_usage` (line 146)
- function: `_format_exports` (line 157)
- function: `_format_exports_resolved` (line 165)
- function: `_format_reexports` (line 175)
- function: `_format_doc_metrics` (line 189)
- function: `_format_typedness` (line 204)
- function: `_format_side_effects` (line 223)
- function: `_format_raises` (line 233)
- function: `_format_complexity` (line 242)
- function: `_format_doc_items` (line 254)
- function: `_format_coverage` (line 281)
- function: `_format_config_refs` (line 292)
- function: `_format_hotspot` (line 299)
- function: `write_markdown_module` (line 306)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 0
- **cycle_group**: 14

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

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
- enrich/README.md

## Hotspot

- score: 2.54

## Side Effects

- filesystem

## Complexity

- branches: 88
- cyclomatic: 89
- loc: 341

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
