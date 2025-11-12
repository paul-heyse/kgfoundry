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
manager immediately applies the overrides to the loaded index.

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
