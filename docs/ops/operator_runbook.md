## Operator Runbook

This runbook captures the day‑to‑day workflow for managing FAISS/DuckDB/SCIP
artifacts. The `indexctl` CLI (installed with `kgfoundry`) is the single source
of truth for lifecycle operations.

### 1. Build & stage

```bash
# Run the indexer in your preferred pipeline.
bin/index_all.py --repo . --out indexes/versions/v1.staging

# Copy staged assets into the lifecycle root (faiss, duckdb, scip, extras).
indexctl stage v1 \
  data/faiss/code.ivfpq.faiss \
  data/catalog.duckdb \
  index.scip \
  --faiss-idmap data/faiss/faiss_idmap.parquet \
  --tuning data/faiss/tuning.json
```

### 2. Publish / rollback

```bash
indexctl publish v1
# At any time:
indexctl rollback v0
# Inspect active version:
indexctl status
indexctl ls
```

Publishing flips `CURRENT`/`current` under the lifecycle root. New artifacts are
always read through `indexes/current/*`.

### 3. Auto‑tune operating points

`tuning.json` lives next to `faiss.index` and is applied automatically on load.
When missing you can sweep runtime parameters directly from DuckDB‑stored
vectors:

```bash
# Fast sweep (nprobe grid)
indexctl tune --quick

# Larger sweep (more nprobe samples)
indexctl tune --full

# Manual overrides (nprobe/efSearch/k-factor)
indexctl tune --nprobe 96 --k-factor 1.8

# Inspect the active profile + overrides
indexctl show-profile
```

Each sweep samples vectors via `duckdb.sample_query_vectors` and writes the
winning ParameterSpace string into `tuning.json`. The runtime audit snapshot is
emitted as `faiss.index.audit.json`.

### 4. ID map + DuckDB joins

The FAISS ID map keeps FAISS row ids in sync with `chunk_id`:

```bash
# Export and refresh materialized join
indexctl export-idmap --out data/faiss/faiss_idmap.parquet --duckdb data/catalog.duckdb

# Re-materialize manually
indexctl materialize-join data/faiss/faiss_idmap.parquet --duckdb data/catalog.duckdb
```

This installs/refreshes the `faiss_idmap`, `faiss_idmap_mat`, and
`v_faiss_join` views so BI queries can stitch FAISS and DuckDB deterministically.

### 5. Pool + coverage analytics

Run the offline evaluator to compare ANN, Flat, and optional XTR rescoring. The
command writes `pool.parquet` and `metrics.json` under
`settings.eval.output_dir` (default `artifacts/eval/`):

```bash
indexctl eval --k 12 --k-factor 2.0 --nprobe 64 --xtr-oracle
```

After the run the CLI wires up DuckDB views:

- `v_faiss_pool` → raw pool rows (FAISS/BM25/SPLADE/XTR hits)
- `v_pool_coverage` → pool rows joined with `chunks` and `modules.jsonl`

Example SQL snippets live in `docs/sql/coverage_examples.sql`.

### 6. Quick reference

| Action | Command |
| ------ | ------- |
| Stage assets | `indexctl stage <ver> <faiss> <duckdb> <scip> [--faiss-idmap ... --tuning ...]` |
| Publish staged version | `indexctl publish <ver>` |
| Rollback current | `indexctl rollback <ver>` |
| Auto-tune (quick/full) | `indexctl tune --quick` / `indexctl tune --full` |
| Manual runtime overrides | `indexctl tune --nprobe 96 --k-factor 1.5` |
| Show active tuning profile | `indexctl show-profile` |
| Export FAISS ID map | `indexctl export-idmap --out data/faiss/faiss_idmap.parquet --duckdb data/catalog.duckdb` |
| Offline evaluation | `indexctl eval --k 12 --k-factor 2 --xtr-oracle` |

Keep this runbook up to date whenever new lifecycle verbs or diagnostics ship.
