# enrich/models.py

## Docstring

```
Dataclasses and helpers shared across enrichment stages.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Iterator, MutableMapping
- from **dataclasses** import dataclass, field
- from **typing** import Any, ClassVar
- from **codeintel_rev.enrich.errors** import StageError

## Definitions

- function: `_clone_dict` (line 15)
- function: `_dedupe_strings` (line 32)
- class: `ModuleRecord` (line 56)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 83

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

ModuleRecord

## Doc Health

- **summary**: Dataclasses and helpers shared across enrichment stages.
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

- score: 1.98

## Side Effects

- none detected

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 250

## Doc Coverage

- `_clone_dict` (function): summary=yes, params=ok, examples=no — Return a shallow dict copy safe for JSON serialization.
- `_dedupe_strings` (function): summary=yes, params=ok, examples=no — Return a list of unique stringified values preserving order.
- `ModuleRecord` (class): summary=yes, examples=no — Canonical per-module row emitted to ``modules.jsonl``.

## Tags

low-coverage, public-api
