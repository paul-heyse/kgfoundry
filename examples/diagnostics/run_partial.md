### Run `demo-partial`

*Tool*: `mcp.tool:semantic_pro`
*Session*: `demo-session`
*Status*: error:TimeoutError (hydrate:error)
*Duration*: 18.30 ms

#### Stage durations (ms)
- embed: 4.80 ms
- pool_search: 11.20 ms
- fuse: 2.30 ms

#### Events
- `embed` retrieval.coderank :: coderank.stage_one :: ok (4.80 ms)
- `pool_search` retrieval.faiss :: faiss.search :: ok (6.70 ms)
- `fuse` retrieval.fusion :: semantic_pro.fuse_rrf :: ok (2.30 ms)
- `hydrate` duckdb.catalog :: duckdb.hydrate :: error (0.50 ms)
