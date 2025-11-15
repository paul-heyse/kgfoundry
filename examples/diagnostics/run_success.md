### Run `demo-success`

*Tool*: `mcp.tool:semantic`
*Session*: `demo-session`
*Status*: ok (completed)
*Duration*: 17.80 ms

#### Stage durations (ms)
- embed: 3.20 ms
- pool_search: 7.80 ms
- fuse: 1.40 ms
- hydrate: 5.00 ms
- envelope: 0.40 ms

#### Events
- `embed` io.vllm :: retrieval.embed :: ok (3.20 ms)
- `pool_search` retrieval.faiss :: faiss.search :: ok (5.10 ms)
- `pool_search` retrieval.bm25 :: bm25.search :: ok (2.70 ms)
- `fuse` retrieval.fusion :: semantic.fuse_rrf :: ok (1.40 ms)
- `hydrate` duckdb.catalog :: duckdb.hydrate :: ok (5.00 ms)
- `envelope` mcp.semantic :: semantic.envelope :: ok (0.40 ms)
