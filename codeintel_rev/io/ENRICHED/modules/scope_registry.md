# app/scope_registry.py

## Docstring

```
Session-scoped scope registry for CodeIntel MCP (legacy helper).

This helper predates the Redis-backed :mod:`codeintel_rev.app.scope_store` that
ApplicationContext wires up automatically today. The registry is still available
for standalone tooling, but production adapters should use ``context.scope_store``
directly rather than mutating ``ApplicationContext``.

Key Components
--------------
ScopeRegistry : class
    Thread-safe registry mapping session IDs to ScopeIn dictionaries.

Design Principles
-----------------
- **Thread Safety**: Uses threading.RLock for concurrent access protection
- **LRU Behavior**: Updates timestamps on access for activity-based expiration
- **Immutable Results**: Returns copies of stored scopes to prevent mutation
- **Fail-Safe**: Missing sessions return None rather than raising exceptions

Example Usage
--------------
Initialize registry manually (e.g., in a short-lived script). When running the
full FastAPI app, use ``ApplicationContext.scope_store`` instead—application
contexts are frozen and cannot be reassigned after creation.

>>> registry = ScopeRegistry()
>>> registry.set_scope("session", {"languages": ["python"]})

Store scope for a session:

>>> session_id = "abc123..."
>>> scope = {"languages": ["python"], "include_globs": ["src/**"]}
>>> registry.set_scope(session_id, scope)

Retrieve scope in adapter:

>>> scope = registry.get_scope(session_id)
>>> if scope:
...     # Apply scope filters
...     include_globs = scope.get("include_globs")

Prune expired sessions (background task):

>>> pruned = registry.prune_expired(max_age_seconds=3600)
>>> logger.info(f"Pruned {pruned} expired sessions")

See Also
--------
codeintel_rev.app.middleware : Session ID extraction and ContextVar management
codeintel_rev.mcp_server.scope_utils : Scope merging and filtering utilities
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import time
- from **copy** import deepcopy
- from **threading** import RLock
- from **typing** import TYPE_CHECKING, cast
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_counter, build_gauge
- from **codeintel_rev.mcp_server.schemas** import ScopeIn

## Definitions

- variable: `LOGGER` (line 66)
- class: `ScopeRegistry` (line 81)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 20

## Declared Exports (__all__)

ScopeRegistry

## Doc Metrics

- **summary**: Session-scoped scope registry for CodeIntel MCP (legacy helper).
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- none detected

## Complexity

- branches: 12
- cyclomatic: 13
- loc: 402

## Doc Coverage

- `ScopeRegistry` (class): summary=yes, examples=yes — Thread-safe registry for session-scoped query scopes.

## Tags

public-api
