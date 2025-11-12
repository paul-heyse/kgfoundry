# CodeIntelligence Enrichment (SCIP × Tree‑sitter × LibCST × Pyrefly)

**Drop-in module set** to build a *metadata‑rich* map of your repo by combining:
- **SCIP** index (definitions, refs, relationships)
- **LibCST** (lossless CST, imports, re‑exports, `__all__`, docstrings)
- **Tree‑sitter** (fast structural outline & resilience)
- **Pyrefly / Pyright** (type gaps, strictness drift), optional

The CLI emits JSONL + Markdown per module, plus a repo‑level graph & tag index.
Timestamp: 2025-11-12T02:32:28Z

## Quick start

```bash
# 1) Place this folder at repo root (or within the target subfolder).
#    Example at repo root:
#      ./codeintel_rev/enrich/...
#      ./codeintel_rev/cli_enrich.py
# 2) Install extras (assuming uv or pip):
uv pip install -e ".[scan-plus]"  # or: pip install -e ".[scan-plus]"

# 3) Run (path to SCIP is required; output dir optional)
python -m codeintel_rev.cli_enrich --scip index.json --root . --out codeintel_rev/io/ENRICHED
# or via console script (after adding to pyproject):
codeintel-enrich --scip index.json --root . --out codeintel_rev/io/ENRICHED
```

Outputs (defaults under `codeintel_rev/io/ENRICHED/`):
- `repo_map.json` – top‑level summary (files, symbols, edges, tags, type coverage)
- `modules/*.jsonl` – one JSON object per line (module summaries)
- `modules/*.md` – human‑readable module briefs (imports/exports/defs/tags)
- `graphs/symbol_graph.json` – symbol ↔ file edge list (from SCIP, de‑duplicated)
- `tags/tags_index.yaml` – per‑module tags, plus global tag catalog
- `../io/CST/` – repo‑wide LibCST dataset built via `codeintel-cst` (see `docs/cst_data.md`)

## Operational notes

- **Re‑exports**: star imports resolved by (1) `__all__` literals, (2) SCIP export/occurrence
  provenance, (3) fallback heuristics. Where resolution is ambiguous, we record evidence and
  confidence levels so LLMs can reason about the gap instead of silently missing symbols.
- **Type coverage**: pulls from Pyrefly and/or Pyright JSON if provided; otherwise optional.
- **Graceful degradation**: LibCST→AST→Tree‑sitter fallback pipeline ensures we *always* emit a
  record, even on tricky files.
- **Custom tags**: Add rules in `enrich/tagging_rules.yaml`—useful to steer LLM agents during
  refactors (e.g., `refactor:io-bound`, `api:public`, `risk:reexport-hub`, `status:needs-types`).

See in‑file docstrings for more details.

## LibCST dataset (`codeintel-cst`)

The enrichment CLI now ships with a dedicated CST pipeline that emits node-level JSONL with
LibCST metadata pre-stitched to modules and SCIP. Run it whenever you regenerate
`modules.jsonl` so stitching stays in sync:

```bash
codeintel-cst \
  --root codeintel_rev \
  --scip codeintel_rev/index.scip.json \
  --modules build/enrich/modules/modules.jsonl \
  --out io/CST
```

Artifacts (documented in `docs/cst_data.md`) land under `io/CST/` and include:

- `cst_nodes.jsonl.gz` – gzip-compressed repo-wide node feed
- `module_nodes/*.jsonl` – per-module slices (matching module paths)
- `index.json` – build metadata, provider stats, and stitch counts
- `joins/stitched_examples.md` – random sample of CST ↔ SCIP joins for QA

Use `--fail-on-parse-error` to make parse failures fatal during CI and `--include/--exclude`
for scoped indexing during debugging.
