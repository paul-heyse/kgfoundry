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

- class: `SupportsAsyncRedis` (line 23)
- function: `get` (line 26)
- function: `setex` (line 29)
- function: `set` (line 32)
- function: `delete` (line 35)
- function: `close` (line 38)
- class: `_CacheRecord` (line 43)
- class: `LRUCache` (line 50)
- function: `__init__` (line 71)
- function: `get` (line 92)
- function: `set` (line 118)
- function: `delete` (line 127)
- function: `clear` (line 132)
- function: `__contains__` (line 137)
- function: `__len__` (line 166)
- function: `items` (line 179)
- function: `snapshot` (line 196)
- function: `_enforce_size` (line 209)
- function: `_purge_expired_entries` (line 213)
- function: `_is_expired` (line 224)
- function: `_has_expired` (line 229)
- class: `AsyncSingleFlight` (line 235)
- function: `__init__` (line 238)
- function: `do` (line 242)
- function: `_execute` (line 266)
- class: `ScopeStoreMetrics` (line 275)
- function: `record_l1_hit` (line 283)
- function: `record_l1_miss` (line 299)
- function: `record_l2_hit` (line 315)
- function: `record_l2_miss` (line 331)
- function: `l1_hit_rate` (line 348)
- function: `l2_hit_rate` (line 354)
- function: `as_dict` (line 359)
- class: `ScopeStore` (line 378)
- function: `__init__` (line 381)
- function: `metrics` (line 402)
- function: `get` (line 406)
- function: `set` (line 437)
- function: `delete` (line 470)
- function: `evict_l1` (line 491)
- function: `close` (line 511)
- function: `_redis_key` (line 515)
- function: `_fetch_from_l2` (line 518)

## Tags

overlay-needed, public-api
