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
- `analytics/ownership.parquet` – Git ownership + churn analytics (owner, primary authors, bus factor, churn windows)
- `slices/` – optional LLM slice packs (`slices/<slice_id>/{slice.json,context.md}` + `slices/index.parquet` + `slices/slices.jsonl`)
- `tags/tags_index.yaml` – per‑module tags, plus global tag catalog
- `../io/CST/` – repo‑wide LibCST dataset built via `codeintel-cst` (see `docs/cst_data.md`)
- `ast/ast_nodes.parquet` / `ast/ast_nodes.jsonl` – Python AST nodes w/ qualnames, decorators, bases, docstrings
- `ast/ast_metrics.parquet` / `ast/ast_metrics.jsonl` – per-file counts (functions/classes/imports), branch metrics, cyclomatic/cognitive complexity

## Data artifacts

The AST layer adds two tables (Parquet + JSONL mirrors) that slot directly into DuckDB/Polars/Pandas workflows:

| Table | Purpose | Key columns |
| ----- | ------- | ----------- |
| `ast/ast_nodes.parquet` | Function/class/module inventory with qualnames and locations | `path`, `module`, `qualname`, `node_type`, `parent_qualname`, `decorators`, `bases`, `docstring`, `is_public` |
| `ast/ast_metrics.parquet` | File-level metrics derived from the Python `ast` module | `path`, `func_count`, `class_count`, `assign_count`, `import_count`, `branch_nodes`, `cyclomatic`, `cognitive`, `max_nesting`, `statements` |
| `analytics/ownership.parquet` | Git ownership + churn snapshots per file | `path`, `owner`, `primary_authors`, `bus_factor`, `recent_churn_30`, `recent_churn_90` (or custom window) |
| `slices/index.parquet` | Catalog of emitted slice packs (opt-in) | `slice_id`, `path`, `module_name` |

Execute `python tools/run_duckdb_demo.py` to load the default script (`tools/demo_duckdb_ast.sql`) and print representative query results. The SQL file shows how to join AST data with `modules.jsonl` (LibCST) and the SCIP symbol graph. Example query:

```sql
WITH exports AS (
  SELECT path, UNNEST(exports) AS exported
  FROM read_json_auto('codeintel_rev/io/ENRICHED/modules/modules.jsonl')
  WHERE array_length(exports) > 0
)
SELECT n.path, n.qualname, n.name, n.node_type
FROM read_parquet('codeintel_rev/io/ENRICHED/ast/ast_nodes.parquet') n
JOIN exports e ON e.path = n.path AND (n.name = e.exported OR n.qualname LIKE e.exported || '%')
ORDER BY n.path, n.qualname;
```

This surfaces AST definitions that are exported via `__all__`, which makes it easy to reconcile LibCST-derived exports with the AST inventory you just captured.

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
