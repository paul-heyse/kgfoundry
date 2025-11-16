# mcp_server/server_semantic.py

## Docstring

```
Semantic MCP tool registrations (pure move from server.py).
```

## Imports

- from **__future__** import annotations
- from **typing** import Any
- from **codeintel_rev.mcp_server.adapters** import deep_research
- from **codeintel_rev.mcp_server.adapters** import semantic
- from **codeintel_rev.mcp_server.adapters** import semantic_pro
- from **codeintel_rev.mcp_server.error_handling** import handle_adapter_errors
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, FetchStructuredContent, FetchToolArgs, SearchFilterPayload, SearchStructuredContent, SearchToolArgs
- from **codeintel_rev.mcp_server.server** import get_context, mcp

## Definitions

- function: `deep_research_search` (line 27)
- function: `deep_research_fetch` (line 83)
- function: `semantic_search` (line 125)
- function: `semantic_search_pro` (line 171)
- function: `telemetry_run_report` (line 227)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 128

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Semantic MCP tool registrations (pure move from server.py).
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

- score: 1.80

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 248

## Doc Coverage

- `deep_research_search` (function): summary=yes, params=ok, examples=no — Deep-Research compatible semantic search that returns chunk ids.
- `deep_research_fetch` (function): summary=yes, params=ok, examples=no — Hydrate chunk ids produced by :func:`deep_research_search`.
- `semantic_search` (function): summary=yes, params=ok, examples=no — Semantic code search using embeddings.
- `semantic_search_pro` (function): summary=yes, params=ok, examples=no — Two-stage semantic retrieval with optional late interaction and reranker.
- `telemetry_run_report` (function): summary=yes, params=ok, examples=no — Return placeholder data because legacy run reports have been removed.

## Tags

low-coverage
