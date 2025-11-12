# `indexctl` CLI reference

The `indexctl` Typer app (entry point `codeintel_rev.cli.indexctl`) manages the
versioned DuckDB/FAISS/SCIP assets and tuning workflows. This document collects
the verbs relevant to FAISS builds, lifecycle management, and evaluators.

## Lifecycle

| Command | Purpose |
| --- | --- |
| `indexctl status` | Show current published version plus available versions. |
| `indexctl ls` | List all published versions. |
| `indexctl stage <version> <faiss> <duckdb> <scip> [--extra channel=/path]...` | Copy artifacts into the lifecycle root (typically `indexes/versions/<version>`). |
| `indexctl publish <version>` | Atomically flip `CURRENT` to the staged version. |
| `indexctl rollback <version>` | Repoint `CURRENT` to a previously published version. |

Extras are specified as `name=/abs/path` (e.g. `--extra bm25=/tmp/bm25`).

## FAISS + DuckDB helpers

| Command | Purpose |
| --- | --- |
| `indexctl export-idmap [--index PATH] [--out PATH] [--duckdb PATH]` | Export `{faiss_row → chunk_id}` to Parquet and (optionally) refresh DuckDB views. |
| `indexctl materialize-join <idmap.parquet> [--duckdb PATH]` | Refresh the DuckDB materialized FAISS join if the checksum differs. |
| `indexctl tune [--nprobe N] [--ef-search N] [--quantizer-ef-search N] [--k-factor F]` | Apply individual runtime overrides; writes `<index>.audit.json` and updates `faiss.meta.json`. |
| `indexctl tune-params "nprobe=64,quantizer_efSearch=64,k_factor=1.5"` | Apply composite FAISS ParameterSpace strings (validated before applying). |
| `indexctl eval [--k 10] [--k-factor 2.0] [--nprobe N] [--xtr-oracle/--no-xtr-oracle]` | Run offline evaluation (FAISS vs Flat, optionally XTR). Outputs live in `settings.eval.output_dir`. |

### Evaluation artifacts

Running `indexctl eval` writes:

* `<output_dir>/last_eval_pool.parquet` – pooled candidates with `source ∈ {faiss, oracle, xtr}`.
* `<output_dir>/metrics.json` – summary payload:

```json
{
  "queries": 32,
  "k": 10,
  "k_factor": 2.0,
  "nprobe": 96,
  "recall_at_k": 0.94,
  "oracle_matches": 300,
  "ann_hits": 320,
  "xtr_records": 320
}
```

## Metadata sidecar (`faiss.meta.json`)

Every successful build and tuning update syncs a metadata file adjacent to the
index. Fields include:

* `factory` – FAISS factory string or adaptive label (`IVF4096,PQ64x8`, `Flat`, etc.).
* `vector_count` – number of vectors in the persisted index.
* `runtime_overrides` – current overrides applied at runtime (`nprobe`, `efSearch`, `k_factor`, etc.).
* `parameter_space` – the last ParameterSpace string applied via `tune-params`.
* `compile_options` – output of `faiss.get_compile_options()` for diagnostics.
* `updated_at` – ISO-8601 timestamp (UTC).

Use this file—together with the `.audit.json` snapshots produced by both tuning
commands—to reason about production configuration or to reproduce an incident.

## Tips

* `indexctl tune` and `indexctl tune-params` both apply overrides immediately to
  the loaded index; no restart is necessary.
* Pair `indexctl eval` with `tune-params` when sweeping nprobe/efSearch: tune a
  parameter string, run evaluation, compare `metrics.json`, repeat.
* The DuckDB helpers assume views live at `data/catalog.duckdb` and Parquet
  vectors under `data/vectors/…`; override via environment or CLI options when
  running in bespoke environments.
