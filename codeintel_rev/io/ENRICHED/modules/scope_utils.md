# mcp_server/scope_utils.py

## Docstring

```
Scope filtering and merging utilities for CodeIntel MCP.

This module provides helper functions for retrieving session scopes, merging them
with explicit adapter parameters, and applying path/language filters to search results.

Key Functions
-------------
get_effective_scope : Retrieve session scope from registry
merge_scope_filters : Merge session scope with explicit parameters (explicit wins)
apply_path_filters : Filter paths using glob patterns (fnmatch)
apply_language_filter : Filter paths by programming language extension
path_matches_glob : Test if path matches glob pattern

Design Principles
-----------------
- **Explicit Precedence**: Explicit adapter parameters always override session scope
- **Fail-Safe**: Missing scope or empty filters return unfiltered results
- **Cross-Platform**: Normalize path separators for Windows/Unix compatibility
- **Performance**: Early-exit for empty filters to avoid unnecessary iterations

Example Usage
-------------
Retrieve and merge scope in adapter:

>>> from codeintel_rev.mcp_server.scope_utils import get_effective_scope, merge_scope_filters
>>> session_id = get_session_id()
>>> scope = get_effective_scope(context, session_id)
>>> merged = merge_scope_filters(scope, {"include_globs": ["src/**"]})
>>> # merged["include_globs"] is now ["src/**"] (explicit overrides scope)

Filter paths by glob patterns:

>>> from codeintel_rev.mcp_server.scope_utils import apply_path_filters
>>> paths = ["src/main.py", "tests/test_main.py", "docs/README.md"]
>>> filtered = apply_path_filters(paths, include_globs=["**/*.py"], exclude_globs=["**/test_*.py"])
>>> filtered
['src/main.py']

Filter paths by language:

>>> from codeintel_rev.mcp_server.scope_utils import apply_language_filter
>>> paths = ["src/main.py", "src/app.ts", "README.md"]
>>> filtered = apply_language_filter(paths, ["python"])
>>> filtered
['src/main.py']

See Also
--------
codeintel_rev.app.scope_store : ScopeStore for storing session scopes
codeintel_rev.app.middleware : get_session_id for retrieving session ID
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import fnmatch
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_histogram
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.mcp_server.schemas** import ScopeIn

## Definitions

- variable: `LOGGER` (line 66)
- variable: `LANGUAGE_EXTENSIONS` (line 77)
- function: `get_effective_scope` (line 116)
- function: `merge_scope_filters` (line 160)
- function: `apply_path_filters` (line 235)
- function: `apply_language_filter` (line 324)
- function: `path_matches_glob` (line 418)

## Dependency Graph

- **fan_in**: 5
- **fan_out**: 3
- **cycle_group**: 42

## Declared Exports (__all__)

LANGUAGE_EXTENSIONS, apply_language_filter, apply_path_filters, get_effective_scope, merge_scope_filters, path_matches_glob

## Tags

public-api
