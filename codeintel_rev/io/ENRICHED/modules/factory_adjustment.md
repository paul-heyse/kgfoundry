# runtime/factory_adjustment.py

## Docstring

```
Factory adjustment hooks for RuntimeCell initialization.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **types** import TracebackType
- from **typing** import Any, Protocol, TypeVar, cast

## Definitions

- variable: `T` (line 10)
- class: `FactoryAdjuster` (line 13)
- class: `NoopFactoryAdjuster` (line 47)
- class: `DefaultFactoryAdjuster` (line 75)
- class: `SuppressException` (line 225)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 29

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DefaultFactoryAdjuster, FactoryAdjuster, NoopFactoryAdjuster

## Doc Health

- **summary**: Factory adjustment hooks for RuntimeCell initialization.
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

- score: 2.19

## Side Effects

- none detected

## Complexity

- branches: 20
- cyclomatic: 21
- loc: 241

## Doc Coverage

- `FactoryAdjuster` (class): summary=yes, examples=no — Protocol for wrapping runtime cell factory functions.
- `NoopFactoryAdjuster` (class): summary=yes, examples=no — Default adjuster that returns the original factory.
- `DefaultFactoryAdjuster` (class): summary=yes, examples=no — Reference adjuster that tunes common runtimes after creation.
- `SuppressException` (class): summary=yes, examples=no — Context manager that suppresses adjustment failures.

## Tags

low-coverage, public-api
