# app/scope_store.py

## Docstring

```
Scope store utilities for session state management.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import time
- from **collections** import OrderedDict
- from **collections.abc** import Awaitable, Callable, Hashable, Iterator, MutableMapping
- from **dataclasses** import dataclass
- from **threading** import RLock
- from **typing** import TYPE_CHECKING, Any, Protocol, cast
- from **(absolute)** import msgspec
- from **codeintel_rev.mcp_server.schemas** import ScopeIn

## Definitions

- variable: `ScopeMapping` (line 18)
- variable: `ScopeIn` (line 20)
- class: `SupportsAsyncRedis` (line 23)
- class: `_CacheRecord` (line 43)
- class: `LRUCache` (line 50)
- class: `AsyncSingleFlight` (line 235)
- class: `ScopeStoreMetrics` (line 275)
- class: `ScopeStore` (line 378)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 30

## Declared Exports (__all__)

AsyncSingleFlight, LRUCache, ScopeStore, ScopeStoreMetrics

## Tags

public-api
