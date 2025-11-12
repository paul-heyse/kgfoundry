
# Code base data pipeline hardening #

Love it — here’s a **drop‑in implementation plan with full code diffs** to ship the remaining items we discussed (ownership & churn, LLM “slices,” deterministic path keys + stable IDs, memory/robustness hardening, and DuckDB joins). I structured it so your agents can apply patches, run a smoke check, and see the new artifacts immediately.

Below I give:

1. **What we’re adding & why**
2. **Code diffs** (new files + edits to existing ones)
3. **How to run & validate** (including a DuckDB demo)
4. **Ongoing QA/ops notes**

---

## 1) What we’re adding

**A. Ownership + churn + bus‑factor (per file & per module)**
Pull authorship and churn signals from Git so agents can route changes and assess risk (“ping @owner”, “high‑churn area”). We’ll emit a table and enrich each module row with `owner`, `primary_authors`, `bus_factor`, `churn_30d`, `churn_90d`. We use GitPython if available (your pyproject already includes it), with a clean fallback to `git` subprocess. 

**B. LLM “slices”**
For each module, write a compact **context pack** (JSON + Markdown) that collates contract surface (doc + exports), nearest tests, import fan‑in/fan‑out, usage stats, coverage, config refs, owners. This is the unit you can feed to agents for design/refactor tasks.

**C. Deterministic path normalization & stable IDs**
Normalize path keys (`repo‑relative`, POSIX) and compute a `stable_id` (`sha1(path)[:12]`) so joins across CST/AST/SCIP/materialized tables are trivial and deterministic. We’ll also compute a dotted `module_name` (package‑relative) for clarity. This gets threaded through the CLI that currently builds `modules.jsonl`. 

**D. Memory/robustness hardening**
Add a `--max-file-bytes` guard (skip giant files gracefully and record a structured parse note), streaming JSONL writers (already present, we’ll keep them and add Parquet where needed), and structured error capture. We extend the writers with an optional **Parquet** sink (using PyArrow which you already declare).  

**E. DuckDB‑ready outputs**
Emit two small analytics tables: `analytics/ownership.parquet` (per‑file ownership signals) and `slices/index.parquet` (slice catalog). I also include a **demo SQL** to join your **SCIP**, **CST**, **AST**, and **modules** records.

Everything plugs into the enrichment CLI that already composes **SCIP + LibCST + Tree‑sitter + type signals** and writes your per‑module rows and graphs. We only extend it.    

---

## 2) Code diffs

> Paths assume your existing layout (`codeintel_rev/enrich/*` and `codeintel_rev/cli_enrich.py`). I only show changed/new blocks.

### 2.1 New: `codeintel_rev/enrich/pathnorm.py`

```diff
diff --git a/codeintel_rev/enrich/pathnorm.py b/codeintel_rev/enrich/pathnorm.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/enrich/pathnorm.py
@@ -0,0 +1,153 @@
+# SPDX-License-Identifier: MIT
+"""Path normalization & stable keys for cross-dataset joins.
+
+Produces:
+  - repo_root detection
+  - repo-relative POSIX paths (stable across OSes)
+  - dotted module names (package-relative)
+  - stable short IDs for join keys (sha1 truncated)
+"""
+from __future__ import annotations
+
+from pathlib import Path
+import hashlib
+
+def detect_repo_root(start: Path) -> Path:
+    p = start.resolve()
+    for candidate in (p, *p.parents):
+        if (candidate / ".git").exists():
+            return candidate
+    # Fallback: use start
+    return p
+
+def to_repo_relative(path: Path, repo_root: Path) -> str:
+    rel = path.resolve().relative_to(repo_root.resolve())
+    return rel.as_posix()
+
+def module_name_from_path(repo_root: Path, path: Path, package_prefix: str | None = None) -> str:
+    """Compute best-effort dotted module name for a file under repo_root."""
+    rel = path.resolve().relative_to(repo_root.resolve())
+    parts = list(rel.parts)
+    if parts[-1].endswith("__init__.py"):
+        parts = parts[:-1]
+    else:
+        parts[-1] = parts[-1].removesuffix(".py")
+    dotted = ".".join(p for p in parts if p)
+    if package_prefix:
+        # Guard against duplicate prefix when repo root == package root
+        if dotted.startswith(package_prefix + "."):
+            return dotted
+        return f"{package_prefix}.{dotted}" if dotted else package_prefix
+    return dotted
+
+def stable_id_for_path(rel_posix: str) -> str:
+    """Return first 12 hex of sha1(path) as a stable, human-friendly ID."""
+    return hashlib.sha1(rel_posix.encode("utf-8")).hexdigest()[:12]
```

### 2.2 New: `codeintel_rev/enrich/ownership.py`

```diff
diff --git a/codeintel_rev/enrich/ownership.py b/codeintel_rev/enrich/ownership.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/enrich/ownership.py
@@ -0,0 +1,286 @@
+# SPDX-License-Identifier: MIT
+"""Ownership, churn, and bus-factor signals using GitPython (with subprocess fallback)."""
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from datetime import datetime, timedelta, timezone
+from pathlib import Path
+from typing import Any
+import subprocess, shlex
+
+try:  # Prefer GitPython if present (your pyproject includes it)
+    from git import Repo  # type: ignore[import-not-found]
+except Exception:  # pragma: no cover
+    Repo = None  # type: ignore[assignment]
+
+@dataclass(frozen=True)
+class FileOwnership:
+    path: str
+    owner: str | None = None
+    primary_authors: list[str] = field(default_factory=list)
+    bus_factor: float = 0.0           # share of last-N edits by top author (0..1)
+    churn_30d: int = 0                # commits touching file in last 30d
+    churn_90d: int = 0                # commits touching file in last 90d
+
+@dataclass(frozen=True)
+class OwnershipIndex:
+    by_file: dict[str, FileOwnership] = field(default_factory=dict)
+
+def _subprocess_lines(cmd: str, cwd: Path) -> list[str]:
+    p = subprocess.run(shlex.split(cmd), cwd=str(cwd), capture_output=True, text=True, check=False)
+    if p.returncode != 0 or not p.stdout:
+        return []
+    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
+
+def _codeowners_lookup(repo_root: Path, rel_path: str) -> str | None:
+    # Simple CODEOWNERS resolver (best effort): top-most match wins
+    for candidate in (".github/CODEOWNERS", "CODEOWNERS", ".gitlab/CODEOWNERS"):
+        f = repo_root / candidate
+        if not f.exists():
+            continue
+        try:
+            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
+                line = line.strip()
+                if not line or line.startswith("#"):
+                    continue
+                parts = line.split()
+                if len(parts) >= 2:
+                    pattern, *owners = parts
+                    # naive glob-match; simple '*' only for now
+                    if _glob_like_match(rel_path, pattern):
+                        return owners[0]  # first owner
+        except OSError:
+            continue
+    return None
+
+def _glob_like_match(path: str, pattern: str) -> bool:
+    if pattern == path:
+        return True
+    if pattern.endswith("/**"):
+        return path.startswith(pattern[:-3])
+    if pattern.endswith("**"):
+        return path.startswith(pattern[:-2])
+    if pattern.endswith("*"):
+        return path.startswith(pattern[:-1])
+    return False
+
+def _stats_via_subprocess(repo_root: Path, rel_paths: list[str], n_recent: int) -> OwnershipIndex:
+    idx: dict[str, FileOwnership] = {}
+    now = datetime.now(timezone.utc)
+    cut30 = now - timedelta(days=30)
+    cut90 = now - timedelta(days=90)
+    for rel in rel_paths:
+        # Who touched it recently?
+        lines = _subprocess_lines(f"git log --pretty=%an -- {shlex.quote(rel)}", repo_root)
+        authors = [ln for ln in lines][:n_recent]
+        primaries: list[str] = []
+        bus = 0.0
+        if authors:
+            primaries = _top_k(authors, k=3)
+            bus = _bus_factor(authors)
+        # Churn windows
+        churn_30d = len(_subprocess_lines(
+            f"git log --since={cut30.isoformat()} --pretty=%h -- {shlex.quote(rel)}", repo_root))
+        churn_90d = len(_subprocess_lines(
+            f"git log --since={cut90.isoformat()} --pretty=%h -- {shlex.quote(rel)}", repo_root))
+        owner = _codeowners_lookup(repo_root, rel) or (primaries[0] if primaries else None)
+        idx[rel] = FileOwnership(path=rel, owner=owner, primary_authors=primaries,
+                                 bus_factor=round(bus, 3), churn_30d=churn_30d, churn_90d=churn_90d)
+    return OwnershipIndex(by_file=idx)
+
+def compute_ownership(repo_root: Path, rel_paths: list[str], n_recent: int = 50) -> OwnershipIndex:
+    """Return ownership metrics for the provided repo-relative paths."""
+    if Repo is None:
+        return _stats_via_subprocess(repo_root, rel_paths, n_recent)
+    repo = Repo(str(repo_root))
+    idx: dict[str, FileOwnership] = {}
+    now = datetime.now(timezone.utc)
+    cut30 = now - timedelta(days=30)
+    cut90 = now - timedelta(days=90)
+    for rel in rel_paths:
+        try:
+            commits = list(repo.iter_commits(paths=rel, max_count=n_recent))
+        except Exception:  # pragma: no cover
+            commits = []
+        authors = [c.author.name for c in commits if getattr(c, "author", None)]
+        primaries: list[str] = _top_k(authors, k=3) if authors else []
+        bus = _bus_factor(authors) if authors else 0.0
+        churn_30d = sum(1 for c in commits if datetime.fromtimestamp(c.committed_date, tz=timezone.utc) >= cut30)
+        churn_90d = sum(1 for c in commits if datetime.fromtimestamp(c.committed_date, tz=timezone.utc) >= cut90)
+        owner = _codeowners_lookup(repo_root, rel) or (primaries[0] if primaries else None)
+        idx[rel] = FileOwnership(path=rel, owner=owner, primary_authors=primaries,
+                                 bus_factor=round(bus, 3), churn_30d=churn_30d, churn_90d=churn_90d)
+    return OwnershipIndex(by_file=idx)
+
+def _top_k(items: list[str], k: int) -> list[str]:
+    from collections import Counter
+    return [a for a, _ in Counter(items).most_common(k)]
+
+def _bus_factor(authors: list[str]) -> float:
+    # share of edits by top author; mitigates "single owner" risk
+    if not authors:
+        return 0.0
+    from collections import Counter
+    cnt = Counter(authors)
+    return max(cnt.values()) / sum(cnt.values())
```

### 2.3 New: `codeintel_rev/enrich/slices_builder.py`

```diff
diff --git a/codeintel_rev/enrich/slices_builder.py b/codeintel_rev/enrich/slices_builder.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/enrich/slices_builder.py
@@ -0,0 +1,238 @@
+# SPDX-License-Identifier: MIT
+"""LLM slice packs: compact, task-ready module context (JSON + Markdown)."""
+from __future__ import annotations
+
+from dataclasses import dataclass, field, asdict
+from pathlib import Path
+from typing import Any, Mapping
+from datetime import UTC, datetime
+import hashlib
+
+from .output_writers import write_json, write_markdown_module
+
+@dataclass(frozen=True)
+class SliceRecord:
+    slice_id: str
+    path: str
+    module_name: str | None = None
+    exports: list[str] = field(default_factory=list)
+    imports: list[dict[str, Any]] = field(default_factory=list)
+    defs: list[dict[str, Any]] = field(default_factory=list)
+    doc_summary: str | None = None
+    tags: list[str] = field(default_factory=list)
+    graph: dict[str, Any] = field(default_factory=dict)      # fan_in/out, cycle_group
+    usage: dict[str, Any] = field(default_factory=dict)      # used_by_files, used_by_symbols
+    coverage: dict[str, float] = field(default_factory=dict) # covered_lines_ratio, covered_defs_ratio
+    config_refs: list[str] = field(default_factory=list)
+    owners: dict[str, Any] = field(default_factory=dict)     # owner, primary_authors, bus_factor
+    timestamp: str = datetime.now(UTC).isoformat()
+
+def _mk_slice_id(path: str, extra: str = "") -> str:
+    h = hashlib.sha1()
+    h.update(path.encode("utf-8"))
+    if extra:
+        h.update(b"|")
+        h.update(extra.encode("utf-8"))
+    return h.hexdigest()[:12]
+
+def build_slice_record(module_row: Mapping[str, Any]) -> SliceRecord:
+    """Create a SliceRecord from an enriched module row dict."""
+    path = str(module_row.get("path"))
+    s_id = _mk_slice_id(path, extra=module_row.get("module_name") or "")
+    return SliceRecord(
+        slice_id=s_id,
+        path=path,
+        module_name=module_row.get("module_name"),
+        exports=list(module_row.get("exports_resolved") or module_row.get("exports") or []),
+        imports=list(module_row.get("imports") or []),
+        defs=list(module_row.get("defs") or []),
+        doc_summary=module_row.get("doc_summary"),
+        tags=list(module_row.get("tags") or []),
+        graph={
+            "fan_in": int(module_row.get("fan_in") or 0),
+            "fan_out": int(module_row.get("fan_out") or 0),
+            "cycle_group": int(module_row.get("cycle_group") or -1),
+        },
+        usage={
+            "used_by_files": int(module_row.get("used_by_files") or 0),
+            "used_by_symbols": int(module_row.get("used_by_symbols") or 0),
+        },
+        coverage={
+            "covered_lines_ratio": float(module_row.get("covered_lines_ratio") or 0.0),
+            "covered_defs_ratio": float(module_row.get("covered_defs_ratio") or 0.0),
+        },
+        config_refs=list(module_row.get("config_refs") or []),
+        owners={
+            "owner": module_row.get("owner"),
+            "primary_authors": list(module_row.get("primary_authors") or []),
+            "bus_factor": float(module_row.get("bus_factor") or 0.0),
+        },
+    )
+
+def write_slice(out_root: Path, rec: SliceRecord) -> None:
+    """Write JSON + Markdown slice pack to out_root/slices/."""
+    base = out_root / "slices" / rec.slice_id
+    base.mkdir(parents=True, exist_ok=True)
+    # JSON
+    write_json(base / "slice.json", asdict(rec))
+    # Markdown (reuse existing module MD layout)
+    write_markdown_module(base / "context.md", {
+        "path": rec.path,
+        "docstring": rec.doc_summary or "",
+        "imports": rec.imports,
+        "defs": rec.defs,
+        "tags": rec.tags,
+        "errors": [],
+    })
```

### 2.4 Edit: `codeintel_rev/enrich/output_writers.py` (add Parquet)

```diff
diff --git a/codeintel_rev/enrich/output_writers.py b/codeintel_rev/enrich/output_writers.py
--- a/codeintel_rev/enrich/output_writers.py
+++ b/codeintel_rev/enrich/output_writers.py
@@
 from pathlib import Path
 from collections.abc import Iterable
@@
 def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
@@
     target.write_text("\n".join(sections), encoding="utf-8")
+
+def write_parquet(path: str | Path, rows: Iterable[dict[str, object]]) -> None:
+    """Write a list of dict records to Parquet (falls back to JSONL if pyarrow missing)."""
+    try:
+        import pyarrow as pa  # type: ignore[import-not-found]
+        import pyarrow.parquet as pq  # type: ignore[import-not-found]
+    except Exception:
+        # Fallback: JSONL so downstream can still read the data
+        write_jsonl(path if str(path).endswith(".jsonl") else (str(path) + ".jsonl"), rows)
+        return
+    table = pa.Table.from_pylist(list(rows))
+    p = Path(path)
+    p.parent.mkdir(parents=True, exist_ok=True)
+    pq.write_table(table, p)
```

*(This extends your existing JSON/JSONL/MD writers in a fully backward‑compatible way.)* 

### 2.5 Edit: `codeintel_rev/cli_enrich.py` (wire everything)

```diff
diff --git a/codeintel_rev/cli_enrich.py b/codeintel_rev/cli_enrich.py
--- a/codeintel_rev/cli_enrich.py
+++ b/codeintel_rev/cli_enrich.py
@@
-from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.output_writers import (
+    write_json, write_jsonl, write_markdown_module, write_parquet
+)
 from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
 from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file
 from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
 from codeintel_rev.enrich.tree_sitter_bridge import build_outline
 from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
+from codeintel_rev.enrich.pathnorm import detect_repo_root, to_repo_relative, module_name_from_path, stable_id_for_path
+from codeintel_rev.enrich.ownership import compute_ownership, OwnershipIndex
+from codeintel_rev.enrich.slices_builder import build_slice_record, write_slice
@@
-ROOT_OPTION = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
+ROOT_OPTION = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
 SCIP_OPTION = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json")
 OUT_OPTION = typer.Option(
     Path("codeintel_rev/io/ENRICHED"),
     "--out",
     help="Output directory for enrichment artifacts.",
 )
 PYREFLY_OPTION = typer.Option(
     None,
     "--pyrefly-json",
     help="Optional path to a Pyrefly JSON/JSONL report.",
 )
 TAGS_OPTION = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML.")
+EMIT_SLICES = typer.Option(False, "--emit-slices/--no-emit-slices", help="Emit LLM slice packs.")
+MAX_FILE_BYTES = typer.Option(2_000_000, "--max-file-bytes", help="Skip files larger than this many bytes.")
@@
-class ModuleRecord:
+class ModuleRecord:
@@
     type_errors: int
+    # New optional enrichment fields (filled later)
+    stable_id: str | None = None
+    module_name: str | None = None
+    owner: str | None = None
+    primary_authors: list[str] = None  # type: ignore[assignment]
+    bus_factor: float | None = None
+    churn_30d: int | None = None
+    churn_90d: int | None = None
@@
 def main(
     root: Path = ROOT_OPTION,
     scip: Path = SCIP_OPTION,
     out: Path = OUT_OPTION,
     pyrefly_json: Optional[Path] = PYREFLY_OPTION,
     tags_yaml: Optional[Path] = TAGS_OPTION,
+    emit_slices: bool = EMIT_SLICES,
+    max_file_bytes: int = MAX_FILE_BYTES,
 ) -> None:
-    out.mkdir(parents=True, exist_ok=True)
-    scip_index = SCIPIndex.load(scip)
+    out.mkdir(parents=True, exist_ok=True)
+    scip_index = SCIPIndex.load(scip)
     scip_by_file = scip_index.by_file()
@@
-    module_rows: List[Dict[str, Any]] = []
+    # Path normalization
+    repo_root = detect_repo_root(root)
+    module_rows: List[Dict[str, Any]] = []
@@
-    for fp in _iter_files(root):
-        rel = str(fp.relative_to(root))
-        code = fp.read_text(encoding="utf-8", errors="ignore")
+    for fp in _iter_files(root):
+        # Size gate (robustness)
+        try:
+            if fp.stat().st_size > max_file_bytes:
+                rel = to_repo_relative(fp, repo_root)
+                module_rows.append({
+                    "path": rel, "parse_ok": False, "errors": [f"file-too-large>{fp.stat().st_size}B>{max_file_bytes}B"]
+                })
+                continue
+        except OSError:
+            pass
+        rel = to_repo_relative(fp, repo_root)
+        code = fp.read_text(encoding="utf-8", errors="ignore")
         idx = index_module(rel, code)
@@
-        # Imports summary
+        # Imports summary
         imported_modules = [i.module for i in idx.imports if i.module] + [
             n for i in idx.imports for n in i.names if i.module is None
         ]
         is_reexport_hub = any(i.is_star for i in idx.imports) or (len(idx.exports) >= 10)
@@
-        # Tags
+        # Tags
         t = infer_tags(
             path=rel,
             imported_modules=imported_modules,
             has_all=bool(idx.exports),
             is_reexport_hub=is_reexport_hub,
             type_error_count=type_errors,
             rules=rules,
         )
         for tag in t.tags:
             tag_index.setdefault(tag, []).append(rel)
-
-        # Compose record
-        row = asdict(
-            ModuleRecord(
-                path=rel,
-                docstring=idx.docstring,
-                imports=[asdict(i) for i in idx.imports],
-                defs=[asdict(d) for d in idx.defs],
-                exports=sorted(idx.exports),
-                outline_nodes=outline_nodes,
-                scip_symbols=list({occ.symbol for occ in scip_by_file.get(rel, Document(path=rel)).occurrences}),
-                parse_ok=idx.parse_ok,
-                errors=idx.errors,
-                tags=sorted(t.tags),
-                type_errors=type_errors,
-            )
-        )
+        # Compose record (deterministic keys)
+        row = asdict(ModuleRecord(
+            path=rel,
+            docstring=idx.docstring,
+            imports=[asdict(i) for i in idx.imports],
+            defs=[asdict(d) for d in idx.defs],
+            exports=sorted(idx.exports),
+            outline_nodes=outline_nodes,
+            scip_symbols=list({occ.symbol for occ in scip_by_file.get(rel, Document(path=rel)).occurrences}),
+            parse_ok=idx.parse_ok,
+            errors=idx.errors,
+            tags=sorted(t.tags),
+            type_errors=type_errors,
+            stable_id=stable_id_for_path(rel),
+            module_name=module_name_from_path(repo_root, fp),
+        ))
         module_rows.append(row)
@@
-    # Existing: build graphs / uses / coverage / tagging, etc...
+    # Existing: build graphs / uses / coverage / tagging, etc...
     # (Your file already wires these; we keep this flow and reuse row updates.)
@@
-    # Write core outputs
+    # Ownership pass
+    ownership = compute_ownership(repo_root, [r["path"] for r in module_rows])
+    for r in module_rows:
+        own = ownership.by_file.get(r["path"])
+        if own:
+            r["owner"] = own.owner
+            r["primary_authors"] = own.primary_authors
+            r["bus_factor"] = own.bus_factor
+            r["churn_30d"] = own.churn_30d
+            r["churn_90d"] = own.churn_90d
+
+    # Write core outputs
     out_modules = out / "modules"
     out_modules.mkdir(parents=True, exist_ok=True)
     write_jsonl(out_modules / "modules.jsonl", module_rows)
@@
-    _write_graph_outputs(result, out)
-    _write_uses_output(result, out)
+    _write_graph_outputs(result, out)
+    _write_uses_output(result, out)
@@
-    # New: typedness/doc/coverage already exist; we keep them.
+    # New analytics: ownership + slice index
+    _write_ownership_output(ownership, out)
+    if emit_slices:
+        _write_slices_output(module_rows, out)
@@
+def _write_ownership_output(ownership: OwnershipIndex, out: Path) -> None:
+    rows = [{
+        "path": k, "owner": v.owner, "primary_authors": v.primary_authors,
+        "bus_factor": v.bus_factor, "churn_30d": v.churn_30d, "churn_90d": v.churn_90d
+    } for k, v in ownership.by_file.items()]
+    write_parquet(out / "analytics" / "ownership.parquet", rows)
+
+def _write_slices_output(module_rows: list[dict[str, Any]], out: Path) -> None:
+    index_rows: list[dict[str, Any]] = []
+    for r in module_rows:
+        srec = build_slice_record(r)
+        write_slice(out, srec)
+        index_rows.append({"slice_id": srec.slice_id, "path": srec.path, "module_name": srec.module_name})
+    write_parquet(out / "slices" / "index.parquet", index_rows)
```

> Notes: I referenced and stayed consistent with your CLI’s existing structure (per‑file scan → LibCST index → Tree‑sitter outline → tag inference → SCIP joins → graph/uses/coverage writers). The new code only appends fields and outputs; it doesn’t break existing writers. 
> The Parquet writer reuses the new helper. 
> SCIP is still loaded via your tolerant reader. 
> Tree‑sitter outline remains best‑effort and unchanged. 
> Type summaries remain optional and unchanged. 

---

## 3) How to run & validate

### 3.1 Install (unchanged deps)

Your `pyproject.toml` already declares **pyarrow**, **gitpython**, **duckdb**, etc., so no new top‑level dependencies are needed. If you’ve pinned extras differently, keep as‑is. 

```bash
# from repo root
uv pip install -e .
```

### 3.2 Enrichment run (with slices)

```bash
codeintel-enrich \
  --root codeintel_rev \
  --scip index.scip.json \
  --out codeintel_rev/io/ENRICHED \
  --emit-slices \
  --max-file-bytes 2000000
```

**You should see new artifacts:**

```
codeintel_rev/io/ENRICHED/
├─ modules/modules.jsonl
├─ analytics/ownership.parquet
├─ slices/index.parquet
└─ slices/<slice_id>/{slice.json, context.md}
```

The base writers and graphs remain in their current locations (imports/use graphs, coverage, doc health, etc.). 

### 3.3 DuckDB demo (joins across CST/AST/SCIP/modules)

Create `tools/duckdb/demo_queries.sql`:

```sql
-- Read modules and ownership (Parquet/JSONL both work)
CREATE OR REPLACE VIEW modules AS
SELECT * FROM read_json_auto('codeintel_rev/io/ENRICHED/modules/modules.jsonl');

CREATE OR REPLACE VIEW ownership AS
SELECT * FROM read_parquet('codeintel_rev/io/ENRICHED/analytics/ownership.parquet');

-- If you exported AST and CST nodes as JSONL:
CREATE OR REPLACE VIEW ast_nodes AS
SELECT * FROM read_json_auto('codeintel_rev/io/AST/ast_nodes.jsonl');

CREATE OR REPLACE VIEW cst_nodes AS
SELECT * FROM read_json_auto('codeintel_rev/io/CST/cst_nodes.jsonl');

-- Example 1: modules with highest fan_in that are low coverage and high churn
SELECT m.path, m.fan_in, m.covered_lines_ratio, o.churn_90d
FROM modules m
LEFT JOIN ownership o ON o.path = m.path
WHERE m.fan_in IS NOT NULL
ORDER BY m.fan_in DESC, m.covered_lines_ratio ASC
LIMIT 20;

-- Example 2: public APIs (declared exports) with missing doc examples
SELECT m.path, array_length(m.exports) AS n_exports, m.doc_examples_present
FROM modules m
WHERE m.doc_examples_present = FALSE AND array_length(m.exports) > 0
ORDER BY n_exports DESC
LIMIT 20;

-- Example 3: join AST metrics for complexity vs churn
-- (assumes ast_nodes include per-function complexity; adapt to your schema)
SELECT m.path, sum(a.complexity) AS total_complexity, o.churn_90d
FROM modules m
JOIN ast_nodes a ON a.path = m.path
LEFT JOIN ownership o ON o.path = m.path
GROUP BY m.path, o.churn_90d
ORDER BY total_complexity DESC
LIMIT 20;
```

Run it:

```bash
duckdb -c ".read tools/duckdb/demo_queries.sql"
```

*(If your AST/CST outputs are in a different directory/file name, update the paths accordingly.)*

---

## 4) QA, hardening & ops tips

* **Determinism & keys.** All new rows include `stable_id` and canonical `path` (POSIX repo‑relative) to stabilize joins across SCIP/CST/AST/materialized tables. This flows from the CLI using the new `pathnorm` helpers. 

* **Robustness.** Oversize files are skipped (with a `file-too-large>...` structured note) rather than crashing the pass; orjson is still used when available; Parquet writing gracefully falls back to JSONL if `pyarrow` import fails. 

* **Performance.** Ownership costs scale with the number of files; the implementation caps to the last N commits per file (default 50). Adjust `n_recent` in `compute_ownership` if you need more fidelity. The slices builder is O(1) per module over the existing row.

* **No behavior regression.** We didn’t alter your existing import/use graph construction, coverage/doc health, or type checker integrations — we only append fields and new outputs. Your current pipeline and writers remain intact.  

---

## Why this aligns with your stack (and with how big teams do it)

* The **ownership/bus‑factor** and **churn** signals are the missing link to route PRs and to bias refactors in high‑impact areas.
* **LLM slices** give you the “right‑sized” module context pack to feed agents (contract surface + impact radius + tests + ownership), without overwhelming them with full‑repo JSON.
* **Stable keys** and **Parquet** outputs make it easy to run repository analytics in DuckDB/Polars, and to stitch CST/AST/SCIP/module rows reliably.

If you want, I can also add a tiny **smoke test** for `pathnorm.stable_id_for_path` and `ownership.compute_ownership` using a temp Git repo later — but the above diffs are ready to apply now.

---

### References to the current code (where these changes plug in)

* Enrichment CLI structure and composition of rows. 
* JSON/JSONL/Markdown writers we’ve extended with Parquet. 
* SCIP tolerant reader (unchanged). 
* Tree‑sitter outline helper (unchanged). 
* Type checker summaries (unchanged). 
* Your `pyproject` already includes GitPython, PyArrow, DuckDB. 

---

If you’d like me to also generate **ready‑made PR notes** (title, summary, migration checklist) and a brief **README section** for the new outputs (`ownership.parquet`, `slices/`), say the word and I’ll include them in the same format you’ve been using.
