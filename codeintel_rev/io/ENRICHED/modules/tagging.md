# enrich/tagging.py

## Docstring

```
Rule-based tagging helpers for enrichment outputs.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import re
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import yaml

## Definitions

- class: `TagResult` (line 16)
- class: `ModuleTraits` (line 25)
- function: `load_rules` (line 55)
- function: `infer_tags` (line 85)
- function: `_rule_matches` (line 124)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 11

## Doc Metrics

- **summary**: Rule-based tagging helpers for enrichment outputs.
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
- enrich/README.md

## Hotspot Score

- score: 1.91

## Side Effects

- filesystem

## Complexity

- branches: 20
- cyclomatic: 21
- loc: 166

## Doc Coverage

- `TagResult` (class): summary=yes, examples=no — Result of running :func:`infer_tags`.
- `ModuleTraits` (class): summary=yes, examples=no — Traits derived from a module used for tagging.
- `load_rules` (function): summary=yes, params=ok, examples=no — Load tagging rules from ``path`` or fall back to the defaults.
- `infer_tags` (function): summary=yes, params=ok, examples=no — Infer tags based on module metadata.
- `_rule_matches` (function): summary=no, examples=no

## Tags

low-coverage
