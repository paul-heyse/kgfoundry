# CodeIntel Catalog Read APIs

This folder contains:
- `codeintel-catalog-read-apis.yaml` – OpenAPI 3.1 spec for GOID, Call Graph, CFG/DFG read endpoints
- `catalog_http_stubs.py` – FastAPI route stubs that match the spec

## Wire-up (inside the current repo layout)

1. Create a new module: `codeintel_rev/app/routes/catalog_read.py` and paste the stub content.
2. Mount router in `codeintel_rev/app/main.py`:
   ```python
   from codeintel_rev.app.routes import catalog_read
   app.include_router(catalog_read.router)
   ```
3. Implement DuckDB queries in `codeintel_rev/io/duckdb_catalog.py`:
   - `query_goids(...) -> GOIDQueryResult`
   - `query_callgraph(...) -> CallGraphResult`
   - `get_cfg(function_goid: str) -> CFGResult | None`
   - `get_dfg(function_goid: str) -> DFGResult | None`

4. Respect capability and readiness patterns already described in the Architecture Narrative.
   Use the same Problem Details error mapping used by MCP adapters.

## DuckDB schema notes

These APIs read from the following logical views (all created under `registry/migrations/0004_catalog_read_views.sql`):

- `goid_crosswalk`
- `v_catalog_call_edges` (caller/callee GOIDs with callsite metadata)
- `v_catalog_cfg_blocks` (function GOID + normalized block identifiers)
- `v_catalog_cfg_edges` (block-to-block edges with normalized IDs)
- `v_catalog_dfg_nodes` (per-function def/use nodes keyed by GOID)
- `v_catalog_dfg_edges` (def→use edges aligned to the node IDs above)

You can materialize these or publish them as views over your existing AST/CST/SCIP artifacts.
