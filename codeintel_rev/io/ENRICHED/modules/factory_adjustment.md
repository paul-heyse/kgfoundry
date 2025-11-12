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

- class: `FactoryAdjuster` (line 13)
- function: `adjust` (line 16)
- class: `NoopFactoryAdjuster` (line 47)
- function: `adjust` (line 50)
- class: `DefaultFactoryAdjuster` (line 75)
- function: `adjust` (line 86)
- function: `_wrap_faiss` (line 120)
- function: `_wrapped` (line 141)
- function: `_wrap_hybrid` (line 160)
- function: `_wrapped` (line 181)
- function: `_wrap_xtr` (line 203)
- class: `SuppressException` (line 225)
- function: `__enter__` (line 228)
- function: `__exit__` (line 231)

## Tags

overlay-needed, public-api
