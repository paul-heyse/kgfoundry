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

## Definitions

- variable: `orjson` (line 13)
- function: `_dump_json` (line 16)
- function: `write_json` (line 39)
- function: `write_jsonl` (line 46)
- function: `_append_section` (line 56)
- function: `_format_imports` (line 64)
- function: `_format_definitions` (line 83)
- function: `_format_graph_metrics` (line 99)
- function: `_format_exports` (line 108)
- function: `_format_exports_resolved` (line 116)
- function: `_format_reexports` (line 126)
- function: `_format_doc_metrics` (line 140)
- function: `_format_typedness` (line 155)
- function: `_format_side_effects` (line 174)
- function: `_format_raises` (line 184)
- function: `_format_complexity` (line 193)
- function: `_format_doc_items` (line 205)
- function: `_format_coverage` (line 232)
- function: `_format_config_refs` (line 243)
- function: `_format_hotspot` (line 250)
- function: `write_markdown_module` (line 257)

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 0
- **cycle_group**: 12

## Doc Metrics

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

## Hotspot Score

- score: 2.41

## Side Effects

- filesystem

## Complexity

- branches: 76
- cyclomatic: 77
- loc: 290

## Doc Coverage

- `_dump_json` (function): summary=yes, params=ok, examples=no — Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.
- `write_json` (function): summary=yes, params=mismatch, examples=no — Write an object as pretty-printed JSON.
- `write_jsonl` (function): summary=yes, params=mismatch, examples=no — Write newline-delimited JSON records.
- `_append_section` (function): summary=no, examples=no
- `_format_imports` (function): summary=no, examples=no
- `_format_definitions` (function): summary=no, examples=no
- `_format_graph_metrics` (function): summary=no, examples=no
- `_format_exports` (function): summary=no, examples=no
- `_format_exports_resolved` (function): summary=no, examples=no
- `_format_reexports` (function): summary=no, examples=no

## Tags

low-coverage
