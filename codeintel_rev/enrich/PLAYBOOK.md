# CodeIntel Enrichment Playbook

Practical guide for generating and sharing every enrichment artifact the CodeIntel
pipeline produces: SCIP, LibCST datasets, AST Parquet/JSONL, and the per-module
outputs that power DuckDB/LLM workflows.

All commands below assume you are in the repository root (`/home/paul/kgfoundry`)
after running `scripts/bootstrap.sh`.

---

## 1. CLI Cheat Sheet

| Purpose | Command (run from repo root) | Output location |
|---------|-----------------------------|-----------------|
| Build SCIP index (binary + JSON) | `cd codeintel_rev && scip-python index ../src --project-name kgfoundry && scip print --json index.scip > index.scip.json` | `codeintel_rev/index.scip` & `codeintel_rev/index.scip.json` |
| Run enrichment + AST/graph/doc outputs | `uv run python -m codeintel_rev.cli_enrich all --root codeintel_rev --scip codeintel_rev/index.scip.json --out codeintel_rev/io/ENRICHED --emit-ast` | `codeintel_rev/io/ENRICHED/**` (modules, graphs, AST, analytics) |
| Rebuild CST dataset (LibCST + stitching) | `uv run python -m codeintel_rev.cst_build.cst_cli --root codeintel_rev --scip codeintel_rev/index.scip.json --modules codeintel_rev/io/ENRICHED/modules/modules.jsonl --out codeintel_rev/io/CST` | `codeintel_rev/io/CST/**` (cst_nodes.jsonl.gz, index.json, joins) |
| DuckDB AST demo (optional sanity check) | `PYTHONPATH=/home/paul/kgfoundry uv run python -c "import sys,runpy;sys.path=[p for p in sys.path if not p.endswith('/tools')];runpy.run_path('tools/run_duckdb_demo.py', run_name='__main__')" --sql tools/demo_duckdb_ast.sql` | Console summaries (joins AST ↔ LibCST ↔ SCIP) |

> Tip: pass `--only 'pkg/*'` to `codeintel_rev.cli_enrich` to restrict the scan while
> debugging. `--emit-ast/--no-emit-ast` toggles AST outputs if you only need JSONL/Markdown.

---

## 2. Workflow Details

### 2.1 Generate SCIP (Sourcegraph index)

```bash
cd codeintel_rev
scip-python index ../src --project-name kgfoundry
scip print --json index.scip > index.scip.json   # JSON form for downstream tools
```

- `index.scip` (binary) is required for FAISS + XTR builds.
- `index.scip.json` feeds the enrichment CLI and CST stitching (SCIPResolver).
- Refresh these whenever source moves or dependencies change.

### 2.2 Run the enrichment CLI (LibCST + AST + analytics)

```bash
uv run python -m codeintel_rev.cli_enrich all \
  --root codeintel_rev \
  --scip codeintel_rev/index.scip.json \
  --out codeintel_rev/io/ENRICHED \
  --emit-ast
```

Key flags:
- `--pyrefly-json` / `--tags-yaml` / `--coverage-xml` attach optional signals.
- `--emit-ast/--no-emit-ast` controls AST Parquet & JSONL emission.
- `--only "pkg/*"` narrows the scan to a sub-package.

Artifacts land under `codeintel_rev/io/ENRICHED/` (see §3).

### 2.3 Build the CST dataset

```bash
uv run python -m codeintel_rev.cst_build.cst_cli \
  --root codeintel_rev \
  --scip codeintel_rev/index.scip.json \
  --modules codeintel_rev/io/ENRICHED/modules/modules.jsonl \
  --out codeintel_rev/io/CST
```

- Consumes LibCST outputs (`modules.jsonl`) and SCIP occurrences.
- Emits streaming-friendly `cst_nodes.jsonl.gz`, `index.json`, and sampled stitch examples.
- Supports `--fail-on-parse-error` and `--debug-joins` for CI or QA runs.

---

## 3. Artifact Catalog

### 3.1 Enrichment core (LibCST + analytics)

| Path | Description |
|------|-------------|
| `io/ENRICHED/repo_map.json` | Snapshot (`root`, module count, graph stats, tag index) |
| `io/ENRICHED/modules/modules.jsonl` | One JSON row per module: imports, defs, exports, tags, doc health, type stats |
| `io/ENRICHED/modules/*.md` | Human-readable module briefs (imports/exports/defs/tags) |
| `io/ENRICHED/graphs/symbol_graph.json` | SCIP symbol ↔ file edge list |
| `io/ENRICHED/graphs/imports.parquet`, `graphs/uses.parquet` | Import/use graphs for downstream analysis |
| `io/ENRICHED/docs/doc_health.parquet` (+ JSONL mirror) | Docstring coverage and summary flags |
| `io/ENRICHED/coverage/coverage.parquet` | Cobertura-style coverage stats (when `--coverage-xml` provided) |
| `io/ENRICHED/analytics/*` | `typedness.parquet`, `hotspots.parquet` etc. for dashboards |
| `io/ENRICHED/configs/config_index.jsonl` | Config file references per module |

### 3.2 AST datasets (Parquet + JSONL)

| File | Contents |
|------|----------|
| `io/ENRICHED/ast/ast_nodes.parquet` & `.jsonl` | Module/class/function definitions, qualnames, decorators, bases, docstrings, spans |
| `io/ENRICHED/ast/ast_metrics.parquet` & `.jsonl` | Per-file counts (functions/classes/imports/assignments), cyclomatic & cognitive metrics, nesting depth |

Pairs share identical schemas so you can choose Parquet for DuckDB/Polars or JSONL
for quick inspection/Web uploads.

### 3.3 CST dataset

| File | Purpose |
|------|---------|
| `io/CST/cst_nodes.jsonl.gz` | Repo-wide LibCST nodes (`NodeRecord` schema) with stitching metadata |
| `io/CST/index.json` | Build summary (`files_indexed`, `node_rows`, stitch counts, provider stats) |
| `io/CST/joins/stitched_examples.md` | Sampled CST ⇄ SCIP joins for manual QA |

Each node row includes spans, parents, scope labels, qualified names, doc snippets,
call targets, import metadata, and stitch info linking back to modules & SCIP symbols.

---

## 4. Sharing & QA Tips

1. **AST quick sanity check**
   ```bash
   PYTHONPATH=/home/paul/kgfoundry uv run python -c "
   import duckdb; con = duckdb.connect();
   con.execute(\"SELECT COUNT(*) FROM read_parquet('codeintel_rev/io/ENRICHED/ast/ast_nodes.parquet')\").show()
   "
   ```
   Or run `tools/run_duckdb_demo.py` (see table above) for richer joins.

2. **CST integrity** – inspect `codeintel_rev/io/CST/index.json`; `parse_errors: 0`
   indicates the LibCST run succeeded. The sample join file highlights stitched nodes.

3. **Web-friendly exports** – use the JSONL artifacts (`ast_nodes.jsonl`,
   `modules.jsonl`, `cst_nodes.jsonl.gz`) when sharing via ChatGPT or uploading to
   notebooks lacking Parquet support.

4. **Regenerate incrementally** – rerun only the pieces you modified:
   - Changed source? Regenerate SCIP and rerun `cli_enrich`/CST.
   - Tweaked tagging rules or AST logic? Just rerun `cli_enrich`.
   - Need only AST? `python -m codeintel_rev.cli_enrich ast-scan ...` (future flag) or
     reuse `_write_ast_outputs` via `--emit-ast`.

5. **Version control** – artifacts are large; commit only when the repo expects
   generated data (CI, golden snapshots). Otherwise keep them local (`.gitignore`
   already excludes `io/ENRICHED` / `io/CST`).

---

## 5. Further Reading

- `codeintel_rev/enrich/README.md` – deep dive into LibCST/SCIP/tagging design.
- `codeintel_rev/cst_build/cst_schema.py` – data classes describing the CST schema.
- `codeintel_rev/enrich/ast_indexer.py` – AST collection internals and PyArrow schemas.
- `tools/demo_duckdb_ast.sql` + `tools/run_duckdb_demo.py` – ready-made DuckDB queries.

Use this playbook as the “one sheet” when onboarding new folks or running a full
refresh before shipping binaries. Continuous improvements go here whenever new
datasets or flags appear. Happy indexing!
