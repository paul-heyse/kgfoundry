# Index Sidecars & Health Checks

This repository keeps FAISS, DuckDB, and sparse artifacts in lock-step. Every
published version contains the CPU FAISS index plus three sidecars:

| File | Purpose |
| --- | --- |
| `faiss.index.meta.json` | Captures factory string, vector count, runtime overrides. |
| `faiss_idmap.parquet` | Mapping from FAISS row (`faiss_row`) to external chunk id (`external_id`). |
| `tuning.json` | ParameterSpace profile (nprobe/efSearch/k_factor) recorded by autotune or manual sweeps. |

The lifecycle manager copies these files alongside `catalog.duckdb` and
`code.scip` whenever `indexctl stage`/`publish` is invoked. The manifest (`versions/<ver>/version.json`)
contains the checksums so CI/BI jobs can assert integrity without re-reading
large blobs.

## ID Map joins

`faiss_idmap.parquet` is the canonical join key for BI, health checks, and MCP
explainability. A single DuckDB view exposes the mapping:

```sql
CREATE OR REPLACE VIEW faiss_idmap AS
SELECT faiss_row, external_id
FROM read_parquet('data/faiss/faiss_idmap.parquet');

CREATE OR REPLACE VIEW v_faiss_join AS
SELECT c.*, f.faiss_row
FROM chunks AS c
LEFT JOIN faiss_idmap AS f ON f.external_id = c.id;
```

`indexctl export-idmap` writes this file via `FAISSManager.export_idmap()` and
`indexctl materialize-join` / `catalog.register_idmap_parquet()` refresh the
DuckDB materialization. All joins remain columnar, so BI dashboards and
backfills can filter by module, language, or FAISS row id without shelling out
to Python.

## Tuning profiles

`FAISSManager.apply_tuning_profile()` understands the `tuning.json` format,
applying ParameterSpace strings (`nprobe`, `efSearch`, `quantizer_efSearch`)
and the rerank `k_factor` without rebuilding the index. The CLI surface:

```
indexctl tune 'nprobe=64,efSearch=128'
indexctl tune --sweep full
indexctl show-profile
```

writes an audit JSON and persists the profile next to the index. Runtime
searches (`search_with_refine`) expose the resolved `k_factor` and factory name
through the `SearchHit.explain` metadata so downstream channels can reason
about exact rerank decisions.

## Health & smoke tests

Two entry points keep operators honest:

1. `indexctl health` verifies FAISS dimension vs DuckDB embedding dimension,
   idmap row counts vs `index.ntotal`, and whether `v_faiss_join` can be
   materialised. Output is machine-readable JSON for dashboards.
2. `indexctl search --dry-run queries.txt --k 10` embeds newline-delimited
   prompts, runs ANN + exact rerank (hydrating embeddings from DuckDB), and
   prints the ANN vs refined overlap so you can spot recall regressions before
   shipping.

See `scripts/smoke_hardening.sh` for an end-to-end shell wrapper that exports
the ID map, runs the health check, and executes the dry-run search on a handful
of representative prompts.
