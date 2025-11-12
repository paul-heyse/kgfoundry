# runtime/request_context.py

## Docstring

```
Shared request-scoped context variables for runtime components.

These context variables are defined in the runtime package so that both
middleware layers and lower-level runtime primitives (like :mod:`runtime.cells`)
can exchange session metadata without introducing circular imports between the
``codeintel_rev.app`` and ``codeintel_rev.runtime`` packages.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **typing** import Final

## Definitions

- variable: `session_id_var` (line 18)
- variable: `capability_stamp_var` (line 25)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 27

## Declared Exports (__all__)

capability_stamp_var, session_id_var

## Doc Metrics

- **summary**: Shared request-scoped context variables for runtime components.
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

## Hotspot Score

- score: 1.31

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 29

## Tags

low-coverage, public-api
