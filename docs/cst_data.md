# CST Data Build

`codeintel-cst` emits a repo-wide **Concrete Syntax Tree dataset** enriched with LibCST
metadata, module-level signals from `modules.jsonl`, and SCIP-def/use stitching. Each node
becomes one JSON record with stable IDs, spans, qualified names, docstring snippets, and
join evidence so downstream agents can jump between CST, modules, and symbol graphs without
guesswork.

## Running the CLI

Use the same enrichment inputs you already maintain (SCIP index + modules.jsonl):

```bash
# Subfolder run (fast debug)
codeintel-cst \
  --root codeintel_rev/enrich \
  --scip codeintel_rev/index.scip.json \
  --modules build/enrich/modules/modules.jsonl \
  --out io/CST/enrich

# Full repo pass (typical)
codeintel-cst \
  --root codeintel_rev \
  --scip codeintel_rev/index.scip.json \
  --modules build/enrich/modules/modules.jsonl \
  --out io/CST
```

Important flags:

- `--include/--exclude` – glob filters relative to `--root`.
- `--limit` – stop after *N* files for quick iterations.
- `--fail-on-parse-error` – make LibCST failures fatal (default is “emit ParseError node
  + continue”).
- `--debug-joins` – attach candidate data to `stitch.candidates` for heuristics tuning.

## Outputs

All artifacts live under the `--out` directory (default `io/CST/`):

| File/Dir | Purpose |
| --- | --- |
| `cst_nodes.jsonl.gz` | Repo-wide node feed (gzip JSONL). One JSON row per node. |
| `module_nodes/<module>.jsonl` | Per-module slices (“pkg.mod.jsonl”). |
| `index.json` | Build metadata (`schema`, `built_at`, counts, provider stats, stitch totals). |
| `joins/stitched_examples.md` | 10-sample Markdown listing CST↔SCIP joins + evidence. |

Each run logs progress (`[12/310] indexing pkg/foo.py`), row counts, and a 3-row join
preview so you can visually confirm stitching before inspecting the artifacts.

## Schema highlights (`cst/v1`)

Every node row contains:

| Field | Description |
| --- | --- |
| `path` | Repo-relative Python path (matches modules.jsonl + SCIP). |
| `node_id` | BLAKE2s digest of `path:start_line:start_col:kind:name` (stable). |
| `kind` / `name` | LibCST node type + identifier when available. |
| `span` | `{start: [line, col], end: [line, col]}` 1-based positions. |
| `text_preview` | First line (≤120 chars) unless the file exceeds 2 MB. |
| `parents` | Truncated ancestry (`Module`, `ClassDef:Foo`, `FunctionDef:bar`). |
| `scope` | `Global | Class | Function | Comprehension` from `ScopeProvider`. |
| `qnames` | Qualified names (local + `module.Class.func` form). |
| `doc` | `{module: "...", def: "..."}` snippets when docstrings exist. |
| `decorators`, `imports`, `ann`, `is_public` | Optional metadata per node type. |
| `call_target_qnames` | Qualified names for `Call` nodes (from callee metadata). |
| `stitch` | `{module_id, scip_symbol, evidence[], confidence}` join metadata. |

On LibCST parse failure a single `ParseError` node is emitted with `errors[]` populated,
keeping downstream pipelines total.

## Stitching guarantees

`stitch` combines two lookups:

1. **Module join** – exact `path` match against `modules.jsonl`; `module_id` falls back to
   the module path when a dedicated id is absent.
2. **SCIP join** – heuristics over `(path, name, span, qname)` with deterministic scoring:
   `1.0` for exact qname match, `0.8` for name+span, `0.6` for name-only (same line window).

`evidence[]` records the reason (e.g., `["module-path", "qname"]`) and `confidence` stores the
score. When `--debug-joins` is set, we also include `stitch.candidates[]` so you can audit
ambiguous cases in CI artifacts.

## Validation & QA

1. Run `codeintel-cst …` locally.
2. Inspect `io/CST/index.json` → confirm `stitched.with_scip > 0`.
3. Skim `io/CST/joins/stitched_examples.md` – spot-check spans/symbols.
4. Optionally `zcat io/CST/cst_nodes.jsonl.gz | head` to see row shape.

The CI workflow adds a non-gating `cst-build` job that runs the CLI on every PR and uploads
`io/CST/` artifacts for review.

## Assumptions & tradeoffs

- Qualified names rely on LibCST + our module path prefixing for locals; imported symbols
  retain the names LibCST provides (`math.sqrt`, etc.).
- The CLI only traverses `.py` files; overlays (`.pyi`) remain opt-in per existing policy.
- We stream writes per file to avoid unbounded memory usage, so dataset ordering follows the
  file crawl order.
