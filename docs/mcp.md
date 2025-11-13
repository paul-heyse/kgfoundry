# MCP Search + Fetch Tools

The CodeIntel MCP server exposes a Deep-Research-compatible tool pair that maps to
our DuckDB + FAISS retrieval stack. Clients discover these tools via the standard
`/tools/list` endpoint and interact using JSON payloads that match the schemas
below.

## `search`

Semantic/hybrid search that returns chunk identifiers plus enough metadata for an
LLM to decide which chunks to hydrate. Requests accept natural language queries
with optional filters:

```jsonc
{
  "query": "How do we warm up FAISS on startup?",
  "top_k": 12,                  // 1..50; defaults to 12
  "rerank": true,               // enable exact cosine rerank via DuckDB embeddings
  "filters": {
    "lang": ["python"],        // language extension aliases
    "include": ["codeintel_rev/**"],
    "exclude": ["**/tests/**"],
    "symbols": ["symbol:codeintel_rev.faiss.clone"]
  }
}
```

Responses conform to:

```jsonc
{
  "results": [
    {
      "id": "1234",
      "title": "codeintel_rev/io/faiss_manager.py: lines 120-168",
      "url": "repo://codeintel_rev/io/faiss_manager.py#L120-L168",
      "snippet": "def ensure_faiss_ready(...)\n    ...",
      "score": 0.873,
      "source": "faiss_ivf_pq",
      "metadata": {
        "uri": "codeintel_rev/io/faiss_manager.py",
        "start_line": 119,              // 0-indexed chunk bounds
        "end_line": 167,
        "start_byte": 2501,
        "end_byte": 4120,
        "lang": "python",
        "symbols": ["codeintel_rev.faiss.ensure_faiss_ready"],
        "explain": {
          "hit_reason": ["embedding:cosine", "filter:lang=python"],
          "scip": true,
          "ast": false,
          "cst": true
        }
      }
    }
  ],
  "queryEcho": "How do we warm up FAISS on startup?",
  "top_k": 12,
  "limits": ["FAISS GPU disabled - using CPU"]
}
```

## `fetch`

Deterministically hydrates chunk ids returned from `search` and enforces a
soft token budget per response:

```jsonc
{
  "objectIds": ["1234", "5678"],
  "max_tokens": 4000   // 256..16000 (defaults to 4000)
}
```

```jsonc
{
  "objects": [
    {
      "id": "1234",
      "title": "codeintel_rev/io/faiss_manager.py: lines 120-168",
      "url": "repo://codeintel_rev/io/faiss_manager.py#L120-L168",
      "content": "full chunk text …",
      "metadata": {
        "uri": "codeintel_rev/io/faiss_manager.py",
        "start_line": 119,
        "end_line": 167,
        "start_byte": 2501,
        "end_byte": 4120,
        "lang": "python"
      }
    }
  ]
}
```

`content` is truncated when the estimated token count exceeds `max_tokens`
(approx. four characters per token) and always terminates on a line boundary.

## Observability & Pool Logging

* **Metrics** – The pipeline records
  `faiss_ann_latency_seconds`, `faiss_refine_latency_seconds`, and
  `mcp_search_postfilter_density`. Additional histograms capture end-to-end search
  and fetch latency (`mcp_search_latency_seconds`, `mcp_fetch_latency_seconds`).
* **Timeline events** – `tool_operation_scope` emits structured start/finish events
  with `session_id`, `run_id`, and search attributes (fan-out, filters, rerank).
* **Pool writer** – Each search writes `(query_id, channel, rank, chunk_id, score,
  symbol_hits, ast_node_kinds, cst_matches)` rows to
  `${DATA_DIR}/trace/mcp_pool/<run_id>.parquet` using
  :func:`codeintel_rev.eval.pool_writer.write_pool`. These Parquet files can be
  attached to DuckDB via `catalog.ensure_pool_views` for coverage analysis.

## Example Workflow

1. `POST /mcp/tools/search` with the payload above to retrieve chunk ids.
2. Inspect `structuredContent.results` to pick the most relevant ids.
3. `POST /mcp/tools/fetch` with those ids to hydrate the full code spans.
4. Optionally query the emitted pool/parquet files in DuckDB for recall heatmaps.

Both tools share the same lifecycle guarantees as the semantic adapters: indexes
are resolved through the lifecycle `current/` pointer, FAISS readiness is enforced
before each query, and heavy dependencies (duckdb, numpy, faiss) are lazily
imported via the shared :class:`ApplicationContext` cache.
