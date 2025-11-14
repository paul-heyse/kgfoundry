# mcp_server/adapters/deep_research.py

## Docstring

```
Adapters that expose MCP Deep-Research search/fetch semantics.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **collections.abc** import AsyncIterator, Mapping, Sequence
- from **contextlib** import asynccontextmanager
- from **pathlib** import Path
- from **typing** import cast
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.mcp_server.schemas** import FetchObject, FetchObjectMetadata, FetchStructuredContent, FetchToolArgs, SearchResultItem, SearchResultMetadata, SearchStructuredContent, SearchToolArgs
- from **codeintel_rev.observability.timeline** import Timeline
- from **codeintel_rev.retrieval.mcp_search** import FetchDependencies, FetchRequest, FetchResponse, SearchDependencies, SearchFilters, SearchRequest, SearchResponse, run_fetch, run_search
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 37)
- function: `_pool_dir` (line 45)
- function: `_clamp_top_k` (line 49)
- function: `_clamp_max_tokens` (line 54)
- function: `_serialize_search_response` (line 59)
- function: `_serialize_fetch_response` (line 105)
- function: `search` (line 140)
- function: `fetch` (line 218)
- function: `_normalize_object_ids` (line 272)
- function: `_bounded` (line 305)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 149

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

fetch, search

## Doc Health

- **summary**: Adapters that expose MCP Deep-Research search/fetch semantics.
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

- score: 2.08

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 13
- cyclomatic: 14
- loc: 323

## Doc Coverage

- `_pool_dir` (function): summary=no, examples=no
- `_clamp_top_k` (function): summary=no, examples=no
- `_clamp_max_tokens` (function): summary=no, examples=no
- `_serialize_search_response` (function): summary=yes, params=ok, examples=no — Convert an internal search response into MCP structured content.
- `_serialize_fetch_response` (function): summary=yes, params=ok, examples=no — Convert an internal fetch response into MCP structured content.
- `search` (function): summary=yes, params=ok, examples=no — Execute the Deep-Research search pipeline.
- `fetch` (function): summary=yes, params=ok, examples=no — Hydrate chunk ids returned from the MCP search tool.
- `_normalize_object_ids` (function): summary=yes, params=ok, examples=no — Normalize object identifiers while preserving ordering.
- `_bounded` (function): summary=yes, params=mismatch, examples=no — Enforce concurrency and timeout guards for MCP operations.

## Tags

low-coverage, public-api
