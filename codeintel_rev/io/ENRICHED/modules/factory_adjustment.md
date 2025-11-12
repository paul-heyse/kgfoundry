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

## Dependency Graph

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 31

## Declared Exports (__all__)

DefaultFactoryAdjuster, FactoryAdjuster, NoopFactoryAdjuster

## Tags

public-api
