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
- function: `write_markdown_module` (line 140)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 4
