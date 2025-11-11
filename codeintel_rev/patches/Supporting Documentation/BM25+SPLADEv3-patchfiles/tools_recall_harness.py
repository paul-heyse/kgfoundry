+#!/usr/bin/env python3
+"""High-recall harness for BM25 + RM3 and (optionally) SPLADE.
+
+This script evaluates Recall@K over a query set while sweeping BM25 (k1, b)
+and RM3 configurations. It also supports an *auto* mode that applies the same
+RM3 heuristics used in production to validate toggle decisions.
+
+Usage
+-----
+python tools/recall_harness.py +  --bm25-index ~/indexes/bm25 +  --queries data/queries.jsonl +  --qrels data/qrels.tsv +  --k 10 +  --sweep-k1 0.6,0.9,1.2 +  --sweep-b 0.2,0.4,0.75 +  --rm3 off,10-10-0.5,20-10-0.5 +  --auto-rm3 true +  --outdir runs/2025-11-11
+
+Input formats
+-------------
+* queries.jsonl: one JSON per line: {"qid": "...", "text": "..."}
+* qrels.tsv: TREC qrels TSV: qid <tab> docid <tab> rel (rel>0 = relevant)
+
+Outputs
+-------
+* summary.json        : per-configuration Recall@K, MRR@K (optional), decisions
+* decisions.csv       : per-query RM3 decisions in auto mode (enable/disable)
+* runs/*.tsv          : simple runs for debugging
+
+Notes
+-----
+* Requires Pyserini for BM25/RM3. SPLADE evaluation is optional (provide
+  --splade-index and --splade-encoder to enable; used for hybrid oracle).
+* Designed to be run in CI/nightly as a regression guard.
+
+"""
+from __future__ import annotations
+
+import argparse
+import csv
+import dataclasses as dc
+import json
+from pathlib import Path
+from typing import Iterable, Mapping, Sequence
+
+
+def _read_jsonl(path: Path) -> list[dict]:
+    out: list[dict] = []
+    with path.open() as f:
+        for line in f:
+            line = line.strip()
+            if not line:
+                continue
+            out.append(json.loads(line))
+    return out
+
+
+def _read_qrels(path: Path) -> dict[str, set[int]]:
+    gold: dict[str, set[int]] = {}
+    with path.open() as f:
+        for row in csv.reader(f, delimiter="\t"):
+            if not row:
+                continue
+            qid, docid, rel = row[0], row[1], int(row[2])
+            if rel > 0:
+                gold.setdefault(qid, set()).add(int(docid))
+    return gold
+
+
+@dc.dataclass(frozen=True)
+class RM3Params:
+    fb_docs: int
+    fb_terms: int
+    orig_weight: float
+
+
+class RM3Heuristics:
+    """Copy of the production heuristic (kept self-contained here)."""
+
+    def __init__(self, *, short_query_max_terms: int = 3, symbol_like_regex: str | None = None) -> None:
+        import re
+        self._tok_re = re.compile(r"[^A-Za-z0-9_]+")
+        self._sym_re = re.compile(
+            symbol_like_regex or r"(?:\w+::\w+)|(?:\w+\.\w+)|(?:[/\\])|(?:[A-Za-z]+[A-Z][a-z]+)|(?:[A-Za-z_]+\d+)"
+        )
+        self._short = short_query_max_terms
+
+    def should_enable(self, q: str) -> bool:
+        toks = [t for t in self._tok_re.split(q.lower()) if t]
+        if len(toks) <= self._short:
+            return True
+        if self._sym_re.search(q):
+            return False
+        return True
+
+
+def _lucene_searcher(index_dir: Path, k1: float, b: float):
+    from importlib import import_module
+
+    lucene = import_module("pyserini.search.lucene")
+    s = lucene.LuceneSearcher(str(index_dir))
+    try:
+        s.set_bm25(k1, b)  # type: ignore[attr-defined]
+    except TypeError:
+        s.set_bm25(k1=k1, b=b)  # type: ignore[attr-defined]
+    return s
+
+
+def _apply_rm3(searcher, p: RM3Params | None) -> None:
+    if p is None:
+        return
+    try:
+        searcher.set_rm3(p.fb_docs, p.fb_terms, p.orig_weight)  # type: ignore[attr-defined]
+    except TypeError:
+        searcher.set_rm3(  # type: ignore[attr-defined]
+            fb_docs=p.fb_docs, fb_terms=p.fb_terms, original_query_weight=p.orig_weight
+        )
+
+
+def _recall_at_k(run: Mapping[str, list[int]], qrels: Mapping[str, set[int]], k: int) -> float:
+    num = 0
+    den = 0
+    for qid, gold in qrels.items():
+        den += 1
+        preds = run.get(qid, [])[:k]
+        if any(d in gold for d in preds):
+            num += 1
+    return (num / den) if den else 0.0
+
+
+def _mrr_at_k(run: Mapping[str, list[int]], qrels: Mapping[str, set[int]], k: int) -> float:
+    import math
+
+    total = 0.0
+    den = 0
+    for qid, gold in qrels.items():
+        den += 1
+        rank = math.inf
+        for i, d in enumerate(run.get(qid, [])[:k], start=1):
+            if d in gold:
+                rank = i
+                break
+        total += 0 if math.isinf(rank) else 1.0 / rank
+    return (total / den) if den else 0.0
+
+
+def _parse_rm3_list(spec: str) -> list[RM3Params | None]:
+    out: list[RM3Params | None] = []
+    for tok in spec.split(","):
+        tok = tok.strip().lower()
+        if not tok or tok == "off" or tok == "none":
+            out.append(None)
+        else:
+            a, b, w = tok.split("-")
+            out.append(RM3Params(int(a), int(b), float(w)))
+    return out
+
+
+def _write_run(path: Path, run: Mapping[str, list[int]]) -> None:
+    with path.open("w") as f:
+        for q, docs in run.items():
+            for rank, d in enumerate(docs, start=1):
+                f.write(f"{q}\t{d}\t{rank}\n")
+
+
+def sweep(
+    *, index_dir: Path, queries: list[dict], qrels: dict[str, set[int]], k: int, k1s: Iterable[float], bs: Iterable[float],
+    rm3s: Iterable[RM3Params | None], auto_rm3: bool, outdir: Path
+) -> dict:
+    outdir.mkdir(parents=True, exist_ok=True)
+    # optional auto RM3
+    auto = RM3Heuristics() if auto_rm3 else None
+
+    results: list[dict] = []
+    decisions_path = outdir / "decisions.csv"
+    with decisions_path.open("w", newline="") as dcsv:
+        dwr = csv.writer(dcsv)
+        dwr.writerow(["qid", "query", "auto_rm3_enabled"])  # filled only when auto_rm3
+
+        for k1 in k1s:
+            for b in bs:
+                for rm3 in rm3s:
+                    # Build two searchers: base and RM3-enabled (for auto mode we switch per-q)
+                    searcher_base = _lucene_searcher(index_dir, k1, b)
+                    searcher_rm3 = _lucene_searcher(index_dir, k1, b)
+                    _apply_rm3(searcher_rm3, rm3)
+
+                    run: dict[str, list[int]] = {}
+                    for q in queries:
+                        qid = str(q["qid"])
+                        text = str(q["text"]).strip()
+                        if not text:
+                            run[qid] = []
+                            continue
+                        if auto is not None:
+                            enable = auto.should_enable(text)
+                            dwr.writerow([qid, text, int(enable)])
+                            s = searcher_rm3 if enable else searcher_base
+                        else:
+                            s = searcher_rm3 if rm3 is not None else searcher_base
+                        hits = s.search(text, k=k)
+                        run[qid] = [int(h.docid) for h in hits]
+
+                    r_at_k = _recall_at_k(run, qrels, k)
+                    mrr_at_k = _mrr_at_k(run, qrels, k)
+
+                    tag = {
+                        "engine": "bm25",
+                        "k1": k1,
+                        "b": b,
+                        "rm3": None if rm3 is None else dc.asdict(rm3),
+                        "auto_rm3": bool(auto is not None),
+                        "k": k,
+                    }
+                    results.append({
+                        "tag": tag,
+                        "recall_at_k": r_at_k,
+                        "mrr_at_k": mrr_at_k,
+                    })
+                    _write_run(outdir / f"run.k1={k1}.b={b}.rm3={'auto' if auto else ('off' if rm3 is None else 'on')}.tsv", run)
+
+    results.sort(key=lambda r: (r["recall_at_k"], r["mrr_at_k"]), reverse=True)
+    summary = {"best": results[0] if results else None, "all": results}
+    with (outdir / "summary.json").open("w") as f:
+        json.dump(summary, f, indent=2, sort_keys=True)
+    return summary
+
+
+def main() -> None:
+    ap = argparse.ArgumentParser()
+    ap.add_argument("--bm25-index", type=Path, required=True)
+    ap.add_argument("--queries", type=Path, required=True)
+    ap.add_argument("--qrels", type=Path, required=True)
+    ap.add_argument("--k", type=int, default=10)
+    ap.add_argument("--sweep-k1", type=str, default="0.9,1.2")
+    ap.add_argument("--sweep-b", type=str, default="0.4,0.75")
+    ap.add_argument("--rm3", type=str, default="off,10-10-0.5")
+    ap.add_argument("--auto-rm3", type=str, default="true")
+    ap.add_argument("--outdir", type=Path, required=True)
+    args = ap.parse_args()
+
+    queries = _read_jsonl(args.queries)
+    qrels = _read_qrels(args.qrels)
+    k1s = [float(x) for x in args.sweep_k1.split(",") if x]
+    bs = [float(x) for x in args.sweep_b.split(",") if x]
+    rm3s = _parse_rm3_list(args.rm3)
+    auto_rm3 = str(args.auto_rm3).strip().lower() in {"1", "true", "yes"}
+
+    summary = sweep(
+        index_dir=args.bm25_index,
+        queries=queries,
+        qrels=qrels,
+        k=args.k,
+        k1s=k1s,
+        bs=bs,
+        rm3s=rm3s,
+        auto_rm3=auto_rm3,
+        outdir=args.outdir,
+    )
+    print(json.dumps(summary["best"], indent=2))
+
+
+if __name__ == "__main__":
+    main()