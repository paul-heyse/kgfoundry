# overlay_manager.py

## Docstring

```
Targeted overlay manager for opt-in stub generation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **codeintel_rev.module_utils** import normalize_module_name

## Definitions

- class: `OverlayPlan` (line 14)
- function: `select_overlay_candidates` (line 21)
- function: `generate_overlay_stub` (line 62)
- function: `activate_generated_overlays` (line 96)
- function: `_safe_int` (line 130)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 157

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Targeted overlay manager for opt-in stub generation.
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

## Hotspot

- score: 1.69

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 155

## Doc Coverage

- `OverlayPlan` (class): summary=yes, examples=no — Plan describing overlays to generate.
- `select_overlay_candidates` (function): summary=yes, params=ok, examples=no — Return overlay candidates based on re-exports and typedness.
- `generate_overlay_stub` (function): summary=yes, params=ok, examples=no — Write a re-export-only stub for ``plan``.
- `activate_generated_overlays` (function): summary=yes, params=ok, examples=no — Symlink generated overlays into the primary stub path.
- `_safe_int` (function): summary=yes, params=ok, examples=no — Return a best-effort integer conversion.

## Tags

low-coverage
