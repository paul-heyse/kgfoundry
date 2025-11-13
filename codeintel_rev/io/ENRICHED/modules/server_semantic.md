# mcp_server/server_semantic.py

## Docstring

```
Semantic MCP tool registrations (pure move from server.py).
```

## Imports

- from **__future__** import annotations
- from **codeintel_rev.mcp_server.adapters** import semantic
- from **codeintel_rev.mcp_server.adapters** import semantic_pro
- from **codeintel_rev.mcp_server.error_handling** import handle_adapter_errors
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope
- from **codeintel_rev.mcp_server.server** import get_context, mcp
- from **codeintel_rev.mcp_server.telemetry** import tool_operation_scope

## Definitions

- function: `semantic_search` (line 18)
- function: `semantic_search_pro` (line 69)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 122

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

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

- score: 1.68

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 127

## Doc Coverage

- `semantic_search` (function): summary=yes, params=ok, examples=no — Semantic code search using embeddings.
- `semantic_search_pro` (function): summary=yes, params=ok, examples=no — Two-stage semantic retrieval with optional late interaction and reranker.

## Tags

low-coverage
