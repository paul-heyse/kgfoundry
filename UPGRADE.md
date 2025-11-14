# Upgrade Notes

## 2025-03-15 — SCIP+CST+AST pipeline hardening (phase 2)

### Summary

- Added `--dry-run` to every enrichment command so operators can validate discovery and SCIP ingest without writing artifacts.
- LibCST visitors now rely on `ScopeProvider` and `QualifiedNameProvider`, improving export detection alongside a Tree-sitter query path with DFS fallback.
- JSONL writers emit deterministic `orjson` bytes (sorted keys + trailing newline) and Parquet writers use Arrow datasets with ZSTD compression and dictionary encoding.
- DuckDB ingestion now uses `read_json_auto()` + `MERGE`, with `DUCKDB_PRAGMAS`, `USE_DUCKDB_JSON`, and other toggles for safe rollouts.
- SCIP decoding is backed by `msgspec.Struct`, cutting load time while preserving the previous API surface.

### Rollout toggles

| Variable | Default | Description |
| --- | --- | --- |
| `ENRICH_JSONL_WRITER` | `v2` | Set to `v1` to revert to the legacy text-mode JSONL writer. |
| `USE_TS_QUERY` | `1` | Set to `0` to force the DFS-only Tree-sitter path. |
| `USE_DUCKDB_JSON` | `1` | Set to `0` to fall back to the row-wise Python ingestion path. |
| `DUCKDB_PRAGMAS` | *(blank)* | Optional `name=value` pairs applied before ingestion (e.g., `threads=8,memory_limit=4GB`). |

### Benchmarks

| Scenario | Before | After | Notes |
| --- | --- | --- | --- |
| JSONL writer (100k ModuleRecord rows) | 1.21 s | 0.52 s | `orjson` bytes writer on AMD 7950X (Python 3.13). |
| SCIP load (`index.scip.json`, 45k docs) | 3.8 s / 420 MB RSS | 1.4 s / 190 MB RSS | `msgspec.Struct` decoder measured on the same host. |
| DuckDB ingest (50k rows) | 5.6 s | 1.9 s | `read_json_auto` + `MERGE` vs. Python row inserts. |

All numbers were captured on a Ryzen 7950X workstation with NVMe storage and Python 3.13.9.
Exact timings will vary, but the relative improvements should hold across Linux hosts.
