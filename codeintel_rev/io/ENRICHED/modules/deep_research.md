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
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.mcp_server.schemas** import FetchObject, FetchObjectMetadata, FetchStructuredContent, FetchToolArgs, SearchResultItem, SearchResultMetadata, SearchStructuredContent, SearchToolArgs
- from **codeintel_rev.retrieval.mcp_search** import FetchDependencies, FetchRequest, FetchResponse, SearchDependencies, SearchFilters, SearchRequest, SearchResponse, run_fetch, run_search
- from **kgfoundry_common.errors** import VectorSearchError

## Definitions

- function: `_pool_dir` (line 43)
- function: `_clamp_top_k` (line 47)
- function: `_clamp_max_tokens` (line 52)
- function: `_serialize_search_response` (line 57)
- function: `_serialize_fetch_response` (line 103)
- function: `search` (line 138)
- function: `fetch` (line 215)
- function: `_normalize_object_ids` (line 264)
- function: `_bounded` (line 297)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 113

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

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

- score: 2.10

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 332

## Doc Coverage

- `_pool_dir` (function): summary=no, examples=no
- `_clamp_top_k` (function): summary=no, examples=no
- `_clamp_max_tokens` (function): summary=no, examples=no
- `_serialize_search_response` (function): summary=yes, params=ok, examples=no — Convert an internal search response into MCP structured content.
- `_serialize_fetch_response` (function): summary=yes, params=ok, examples=no — Convert an internal fetch response into MCP structured content.
- `search` (function): summary=yes, params=ok, examples=no — Execute the Deep-Research search pipeline.
- `fetch` (function): summary=yes, params=ok, examples=no — Hydrate chunk ids returned from the MCP search tool.
- `_normalize_object_ids` (function): summary=yes, params=ok, examples=no — Normalize object identifiers while preserving ordering.
- `_bounded` (function): summary=yes, params=ok, examples=no — Enforce concurrency and timeout guards for MCP operations.

## Tags

low-coverage, public-api
