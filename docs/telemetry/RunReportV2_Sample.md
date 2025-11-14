# Run sample-run
- Tool: search.semantic
- Trace ID: sample-run
- Session ID: sample-session
- Stopped because: completed

## Stages
- **gather**: completed (12.50 ms)
- **fuse**: completed (31.20 ms)
- **hydrate**: completed (18.40 ms)
- **rerank**: skipped — budget_exceeded (0.00 ms)

## Discrete Events
- retrieval.gather_channels (completed) payload={'duration_ms': 12.5, 'channels': ['semantic', 'bm25']}
- retrieval.fuse (completed) payload={'duration_ms': 31.2, 'rrf_k': 60}
- duckdb.query (completed) payload={'duration_ms': 18.4, 'rows': 4}
- retrieval.rerank (skipped) payload={'duration_ms': 0.0}

## Span Attributes
```json
{
  "mcp.session_id": "sample-session",
  "mcp.run_id": "sample-run",
  "mcp.tool": "search.semantic",
  "capability_stamp": "cap-123"
}
```
