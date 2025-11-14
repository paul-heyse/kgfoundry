# Run run-xyz789

- Tool: semantic_search
- Trace ID: a1b2c3d4e5f6789012345678901234ab
- Session ID: session-abc123

## Budgets

```json
{
  "rrf_k": 60,
  "per_channel_depths": {
    "faiss": 100,
    "bm25": 150,
    "splade": 120
  },
  "rm3_enabled": true
}
```

## Stages

| Stage | Status | Duration | Detail |
|-------|--------|----------|--------|
| retrieval.gather_channels | ok | 45.20 ms | Gathered hits from FAISS, BM25, SPLADE |
| retrieval.fuse | ok | 12.50 ms | RRF fusion with k=60 |
| duckdb.query | ok | 89.30 ms | Hydrated 200 documents |
| retrieval.recency_boost | ok | 5.10 ms | Applied recency boost to 50 documents |

## Timeline Events

- **10:30:00.000Z** - `request.accepted`: Query normalized and validated
- **10:30:00.050Z** - `embed.done`: Embedding batch completed (batch_size=1, latency_ms=50.0)
- **10:30:00.123Z** - `bm25.hitset`: BM25 search completed (hits=150, top_k=150)

## Warnings

None

## Span Attributes

- `mcp.session_id`: session-abc123
- `mcp.run_id`: run-xyz789
- `mcp.tool`: semantic_search
