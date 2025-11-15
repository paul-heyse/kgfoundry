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

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 2
- **cycle_group**: 38

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

AsyncSingleFlight, LRUCache, ScopeStore, ScopeStoreMetrics

## Doc Health

- **summary**: Scope store utilities for session state management.
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

- app/hypercorn.toml

## Hotspot

- score: 2.33

## Side Effects

- subprocess

## Complexity

- branches: 43
- cyclomatic: 44
- loc: 539

## Doc Coverage

- `SupportsAsyncRedis` (class): summary=yes, examples=no — Protocol describing the Redis operations required by ``ScopeStore``.
- `_CacheRecord` (class): summary=yes, examples=no — Internal cache record containing a value and its insertion timestamp.
- `LRUCache` (class): summary=yes, examples=no — Thread-safe least-recently-used cache with TTL-based eviction.
- `AsyncSingleFlight` (class): summary=yes, examples=no — Deduplicate concurrent coroutine execution keyed by ``KeyT``.
- `ScopeStoreMetrics` (class): summary=yes, examples=no — Runtime counters describing scope store cache performance.
- `ScopeStore` (class): summary=yes, examples=no — Redis-backed scope store with L1/L2 caching and single-flight coalescing.

## Tags

low-coverage, public-api
