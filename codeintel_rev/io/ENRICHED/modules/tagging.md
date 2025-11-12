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
- function: `load_rules` (line 46)
- function: `infer_tags` (line 76)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 10

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

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 128

## Doc Coverage

- `TagResult` (class): summary=yes, examples=no — Result of running :func:`infer_tags`.
- `ModuleTraits` (class): summary=yes, examples=no — Traits derived from a module used for tagging.
- `load_rules` (function): summary=yes, params=ok, examples=no — Load tagging rules from ``path`` or fall back to the defaults.
- `infer_tags` (function): summary=yes, params=ok, examples=no — Infer tags based on module metadata.
