# enrich/slices_builder.py

## Docstring

```
Utilities for generating opt-in LLM slice packs.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping
- from **dataclasses** import asdict, dataclass, field
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any
- from **codeintel_rev.enrich.output_writers** import write_json, write_markdown_module
- from **hashlib** import sha1

## Definitions

- class: `SliceRecord` (line 18)
- function: `_slice_id` (line 38)
- function: `build_slice_record` (line 48)
- function: `write_slice` (line 95)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 19

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

SliceRecord, build_slice_record, write_slice

## Doc Health

- **summary**: Utilities for generating opt-in LLM slice packs.
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

- score: 2.00

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 122

## Doc Coverage

- `SliceRecord` (class): summary=yes, examples=no — Serializable context packet describing a module and its surroundings.
- `_slice_id` (function): summary=no, examples=no
- `build_slice_record` (function): summary=yes, params=mismatch, examples=no — Build a :class:`SliceRecord` from a module row dictionary.
- `write_slice` (function): summary=yes, params=mismatch, examples=no — Persist a slice pack (JSON + Markdown) under ``out_root/slices``.

## Tags

low-coverage, public-api
