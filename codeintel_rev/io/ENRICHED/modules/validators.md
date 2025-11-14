# enrich/validators.py

## Docstring

```
Schema validation helpers for enrichment rows.
```

## Imports

- from **__future__** import annotations
- from **typing** import Any
- from **pydantic** import BaseModel, ConfigDict, Field

## Definitions

- class: `ModuleRecordModel` (line 13)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 87

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

ModuleRecordModel

## Doc Health

- **summary**: Schema validation helpers for enrichment rows.
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

- score: 1.19

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 49

## Doc Coverage

- `ModuleRecordModel` (class): summary=yes, examples=no — Lightweight schema used to validate modules.jsonl rows.

## Tags

low-coverage, public-api, pydantic
