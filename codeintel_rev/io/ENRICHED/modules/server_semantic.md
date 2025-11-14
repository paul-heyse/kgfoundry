# mcp_server/server_semantic.py

## Docstring

```
Semantic MCP tool registrations (pure move from server.py).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **typing** import Any
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.mcp_server.adapters** import deep_research
- from **codeintel_rev.mcp_server.adapters** import semantic
- from **codeintel_rev.mcp_server.adapters** import semantic_pro
- from **codeintel_rev.mcp_server.error_handling** import handle_adapter_errors
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, FetchStructuredContent, FetchToolArgs, SearchFilterPayload, SearchStructuredContent, SearchToolArgs
- from **codeintel_rev.mcp_server.server** import get_context, mcp
- from **codeintel_rev.mcp_server.telemetry** import tool_operation_scope
- from **codeintel_rev.observability.otel** import current_trace_id
- from **codeintel_rev.telemetry.context** import current_session
- from **codeintel_rev.telemetry.reporter** import build_report
- from **codeintel_rev.telemetry.reporter** import report_to_json

## Definitions

- function: `deep_research_search` (line 34)
- function: `deep_research_fetch` (line 96)
- function: `semantic_search` (line 143)
- function: `semantic_search_pro` (line 194)
- function: `telemetry_run_report` (line 255)
- function: `_render_run_report` (line 293)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 10
- **cycle_group**: 144

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

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

- score: 2.34

## Side Effects

- subprocess

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 309

## Doc Coverage

- `deep_research_search` (function): summary=yes, params=ok, examples=no — Deep-Research compatible semantic search that returns chunk ids.
- `deep_research_fetch` (function): summary=yes, params=ok, examples=no — Hydrate chunk ids produced by :func:`deep_research_search`.
- `semantic_search` (function): summary=yes, params=ok, examples=no — Semantic code search using embeddings.
- `semantic_search_pro` (function): summary=yes, params=ok, examples=no — Two-stage semantic retrieval with optional late interaction and reranker.
- `telemetry_run_report` (function): summary=yes, params=ok, examples=no — Return the latest run report for the active or requested session.
- `_render_run_report` (function): summary=no, examples=no

## Tags

low-coverage
