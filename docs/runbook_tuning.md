# FAISS Tuning Runbook

The FAISS manager now records a metadata sidecar (`*.meta.json`) alongside each
index. The file captures build factory, compile flags, vector counts, and the
current runtime overrides. Use it to reason about production incidents or to
compare parameter sweeps.

## Runtime overrides

Use `indexctl tune` when you want to update a single knob:

```bash
indexctl tune --nprobe 96
indexctl tune --k-factor 1.5
```

`tune` persists a `.audit.json` snapshot that mirrors `faiss.meta.json`. The
manager immediately applies the overrides to the loaded index. To revert to the
last saved profile remove the audit file and reload the application context.

### Quick sweeps

You can now run bounded sweeps against the vectors already stored in DuckDB:

```bash
# ~64 vector sample, nprobe grid
indexctl tune --quick

# Larger (~256 vector) sweep, more nprobe samples
indexctl tune --full
```

The command samples chunk embeddings from `duckdb.sample_query_vectors`, runs a
ParameterSpace sweep, and writes the winning settings to `tuning.json`. These
profiles ship with the index (staged/published alongside `faiss.index`) and are
applied automatically at startup. Use `indexctl show-profile` to inspect the
active profile, overrides, and ParameterSpace string.

## ParameterSpace sweeps

When you need to apply a composite FAISS ParameterSpace string, use the new
`tune-params` verb:

```bash
indexctl tune-params "nprobe=64,quantizer_efSearch=64,k_factor=1.3"
```

The parameter string is validated (positive integers, supported keys) before we
hand it off to FAISS. The string is also recorded in the metadata file so you
can reconstruct the exact runtime state later.

## Offline evaluation

`indexctl eval` compares ANN results against a Flat oracle (and optionally XTR):

```bash
indexctl eval --k 10 --k-factor 2.0 --nprobe 96 --xtr-oracle
```

Results are written under `settings.eval.output_dir`:

- `last_eval_pool.parquet`: pooled candidates with `source` (`faiss`, `oracle`,
  `xtr`).
- `metrics.json`: summary (queries evaluated, k, nprobe, recall@k, matches).

Use these artifacts to spot regressions when tweaking FAISS knobs or after
refreshing the embedding model.
