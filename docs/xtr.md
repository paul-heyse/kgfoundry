## XTR / WARP Late-Interaction Quickstart

XTR (token-level) late interaction powers the Stage-B rescoring path inside
`semantic_pro`. It keeps latency predictable by building a memmap of normalized
token embeddings and running MaxSim on CPU by default while still allowing GPU
engines (WARP executor) when available.

### Build artifacts

```bash
uv run python -m codeintel_rev.cli.xtr build
# or
uv run python -m codeintel_rev.indexing.xtr_build
```

Artifacts are written under `paths.xtr_dir` (default `data/xtr/`) with:

- `tokens.f16` or `tokens.f32` – memmap of token embeddings
- `index.meta.json` – offsets/doclens/dim metadata

Verify readiness locally (also wired into `/readyz`):

```bash
uv run python -m codeintel_rev.cli.xtr verify
```

### Configuration knobs

Environment variables (also exposed via `XTRConfig`):

| Variable | Description | Default |
| --- | --- | --- |
| `XTR_ENABLE` | Toggle Stage-B rescoring | `false` |
| `XTR_DIR` | Artifact directory | `data/xtr` |
| `XTR_MODEL_ID` | HF encoder checkpoint | `nomic-ai/CodeRankEmbed` |
| `XTR_DEVICE` | Query encoding/scoring device | `cuda` |
| `XTR_MAX_QUERY_TOKENS` | Query token cap | `256` |
| `XTR_CANDIDATE_K` | Stage-A candidates to rescore | `200` |
| `XTR_DIM` | Token embedding dimension | `768` |
| `XTR_DTYPE` | Token storage precision | `float16` |

Set `WARP_ENABLED=1` alongside these values to prefer the native WARP executor;
otherwise the built-in `XTRIndex` path is used as the default CPU retriever.

### Observability

- `ReadinessProbe` exposes `xtr_artifacts` with partial failure detail.
- Stage timings include `warp_late_interaction`; method metadata now carries
  `notes` describing gating/skip reasons and `explainability.warp` with top
  query↔code token alignments (≤5 hits, ≤2 KB each).
- Prometheus counters coming from `track_stage` cover the XTR path alongside
  existing `fusion_rrf`, `coderank_ann`, and `duckdb_hydration` timers.
