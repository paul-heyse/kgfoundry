# GUIDE RELEVANT TO OUR DEPLOYMENT IN CODEINTEL #

Absolutely — here’s a single, **fully integrated** playbook that covers **BM25 end-to-end** and **SPLADE-v3 (ONNX, CPU-accelerated)** end-to-end, including export/quantize → encode → index → search (single & batch) → **hybrid RRF**, plus **BM25 tuning**, **evaluation**, and an **optional SPLADE fine-tuning** path (GPU if present, CPU works but slow). I’ve also included an expanded `Makefile`.

Key surfaces we rely on are stable and documented:

* **Pyserini** BM25 search (`LuceneSearcher`), BM25 param control (`set_bm25(k1,b)`), batch search & run files, and SPLADE **impact** indexing (`JsonVectorCollection` + `--impact --pretokenized`). ([Hugging Face][1])
* The **prebuilt SPLADE-v3 BEIR** indexes use the exact impact-index flags we adopt here, so you’re aligned with upstream practice. ([Hugging Face][2])
* **Sentence-Transformers** `SparseEncoder` with **ONNX backend** and official **export / optimize / quantize** helpers (`export_optimized_onnx_model`, `export_dynamic_quantized_onnx_model`). ([SentenceTransformers][3])
* Pyserini’s built-in **trec_eval** wrapper lets you evaluate run files without extra binaries. ([GitHub][4])
* For long SPLADE queries, you can raise Lucene’s Boolean query clause limit (default 1024) via API/system property. We expose a guard; details & API are well-known. ([lucene.apache.org][5])

---

# `playbook.py` (drop-in CLI)

```python
#!/usr/bin/env python3
"""
SPLADE-v3 (ONNX, CPU) + BM25 with Pyserini — Unified Playbook

Subcommands
-----------
  export        Export SPLADE-v3 to ONNX and (optionally) dynamic-quantize (int8) for CPU.
  prepare-bm25  Normalize corpus.jsonl -> JsonCollection (BM25) directory.
  index-bm25    Build Lucene BM25 index from JsonCollection.
  encode        Encode corpus.jsonl -> JsonVectorCollection with SPLADE (ONNX).
  index-splade  Build Lucene impact index from SPLADE vectors.
  search        One-off search: bm25 | splade | hybrid (RRF).
  search-batch  Batch search from TSV topics; write TREC run file.
  eval          Evaluate a run file against qrels using pyserini.eval.trec_eval.
  tune-bm25     Grid-search BM25 (k1,b) on topics+qrels; reports best config.
  train         (Optional) Finetune SPLADE on triples; saves HF-style model dir.
  bench         Micro-benchmark ONNX query encoding latency.

Data & dirs (defaults)
----------------------
  data/corpus.jsonl         # {"id": "...", "contents" | "text": "..."} per line
  data/jsonl/               # BM25 JsonCollection
  data/splade_vectors/      # SPLADE JsonVectorCollection shards
  indexes/bm25/             # BM25 index
  indexes/splade_v3_impact/ # SPLADE impact index
  models/splade-v3/         # exported ONNX artifacts live under onnx/
"""

from __future__ import annotations
import argparse, os, sys, time, json, subprocess, tempfile
from pathlib import Path
from typing import List, Tuple, Iterable

try:
    import ujson as _json
except Exception:
    _json = json

# ---------------------------
# Helpers
# ---------------------------

def info(x): print(f"[INFO] {x}", flush=True)
def warn(x): print(f"[WARN] {x}", flush=True)
def err(x):  print(f"[ERROR] {x}", file=sys.stderr, flush=True)

def require_path(p: Path, kind="file"):
    if kind == "file" and not p.is_file(): err(f"Missing file: {p}"); sys.exit(1)
    if kind == "dir"  and not p.is_dir():  err(f"Missing dir:  {p}"); sys.exit(1)

def stream_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield _json.loads(line)

def pseudo_bow(decoded: List[Tuple[str, float]], q=100, max_terms=3000) -> str:
    """Repeat tokens proportional to integer impacts (SPLADE impact query convention)."""
    toks = []
    for tok, w in decoded:
        if w <= 0: continue
        iw = int(round(w * q))
        if iw > 0:
            toks.extend([tok] * iw)
        if len(toks) >= max_terms:
            break
    return " ".join(toks[:max_terms])

def write_trec_run(run, out_path: Path, tag="Pyserini"):
    with out_path.open("w", encoding="utf-8") as w:
        for qid, hits in run.items():
            for rank, (docid, score) in enumerate(hits, 1):
                w.write(f"{qid} Q0 {docid} {rank} {score:.6f} {tag}\n")

def rrf_fuse(run_a, run_b, k=60, topk=1000):
    """run_* are lists of (docid, score). Returns fused topk list."""
    scores = {}
    for run in (run_a, run_b):
        for r, (docid, _) in enumerate(run, 1):
            scores[docid] = scores.get(docid, 0.0) + 1.0/(k+r)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:topk]

# ---------------------------
# Subcommands
# ---------------------------

def cmd_export(a):
    """Export SPLADE-v3 to ONNX (+ optional int8 dynamic quant)."""
    from sentence_transformers import SparseEncoder
    info(f"Exporting '{a.model_id}' → ONNX at {a.out_dir}")
    out_dir = Path(a.out_dir); (out_dir / "onnx").mkdir(parents=True, exist_ok=True)

    # Base ONNX export via backend
    enc = SparseEncoder(a.model_id, backend="onnx")
    enc.save_pretrained(str(out_dir))
    base = out_dir / "onnx" / "model.onnx"
    if base.exists():
        info(f"Base ONNX: {base}")
    else:
        warn("ONNX export expected but not found; upgrade sentence-transformers if needed.")

    # Optimize (O3) & quantize (int8)
    if a.optimize:
        from sentence_transformers import export_optimized_onnx_model
        export_optimized_onnx_model(enc, optimization_config="O3",
                                    model_name_or_path=str(out_dir),
                                    push_to_hub=False, create_pr=False)
        info("Saved optimized ONNX (O3).")
    if a.quantize:
        try:
            from onnxruntime.quantization import quantize_dynamic, QuantType
            qpath = out_dir / "onnx" / "model_qint8.onnx"
            quantize_dynamic(str(base), str(qpath), weight_type=QuantType.QInt8, optimize_model=True)
            info(f"Saved int8 dynamic-quantized ONNX: {qpath}")
        except Exception as e:
            warn(f"Quantization skipped (onnxruntime.quantization missing?): {e}")

def cmd_prepare_bm25(a):
    """Normalize corpus.jsonl -> JsonCollection for BM25."""
    src = Path(a.corpus); out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    require_path(src, "file")
    n=0
    for obj in stream_jsonl(src):
        docid = str(obj["id"])
        contents = obj.get("contents") or obj.get("text") or ""
        with (out / f"{docid}.json").open("w", encoding="utf-8") as w:
            _json.dump({"id": docid, "contents": contents}, w)
        n += 1
        if n % 10000 == 0: info(f"wrote {n} docs …")
    info(f"✅ BM25 JsonCollection at {out} ({n} docs)")

def _run_pyserini_index(cmd: List[str]):
    info("Launching: " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        err("Indexing failed"); sys.exit(r.returncode)

def cmd_index_bm25(a):
    """Build BM25 index."""
    cmd = [sys.executable, "-m", "pyserini.index.lucene",
           "--collection", "JsonCollection",
           "--input", a.json_dir,
           "--index", a.index_dir,
           "--generator", "DefaultLuceneDocumentGenerator",
           "--threads", str(a.threads),
           "--storePositions", "--storeDocvectors", "--storeRaw"]
    _run_pyserini_index(cmd)
    info(f"✅ BM25 index at {a.index_dir}")

def cmd_encode(a):
    """Encode corpus.jsonl -> JsonVectorCollection using SPLADE (ONNX)."""
    from sentence_transformers import SparseEncoder
    from tqdm import tqdm

    src = Path(a.corpus); out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    require_path(src, "file")
    model_kwargs = {"provider": a.provider}
    if a.onnx_file:
        model_kwargs["file_name"] = a.onnx_file
    enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=model_kwargs)

    def to_vec(decoded):
        v={}
        for tok, w in decoded:
            if w>0:
                iw=int(round(w*a.quant))
                if iw>0: v[tok]=iw
        return v

    batch_ids, batch_texts = [], []
    shard_i, n = 0, 0
    writer=None
    def open_writer(i): return (out / f"part-{i:05d}.jsonl").open("w", encoding="utf-8")
    def flush():
        nonlocal writer, shard_i, n
        if not batch_texts: return
        emb = enc.encode_document(batch_texts)
        decs = enc.decode(emb, top_k=None)
        for docid, dec in zip(batch_ids, decs):
            rec = {"id": docid, "contents": "", "vector": to_vec(dec)}
            if writer is None: writer = open_writer(shard_i)
            writer.write(_json.dumps(rec) + "\n")
            n += 1
            if n % a.shard_size == 0:
                writer.close(); writer=None; shard_i+=1
        batch_ids.clear(); batch_texts.clear()

    info(f"Encoding with ONNX: model_dir={a.model_dir}, file={a.onnx_file}, provider={a.provider}")
    for obj in tqdm(stream_jsonl(src), desc="encode-docs"):
        docid = str(obj["id"]); text = obj.get("contents") or obj.get("text") or ""
        batch_ids.append(docid); batch_texts.append(text)
        if len(batch_texts) >= a.batch: flush()
    flush()
    if writer: writer.close()
    info(f"✅ Wrote {n} vectors to {a.out_dir}")

def cmd_index_splade(a):
    """Build Lucene impact index from JsonVectorCollection."""
    # Helpful when SPLADE expands queries a lot:
    os.environ.setdefault("JAVA_TOOL_OPTIONS", f"-Dorg.apache.lucene.maxClauseCount={a.max_clause}")
    cmd = [sys.executable, "-m", "pyserini.index.lucene",
           "--collection", "JsonVectorCollection",
           "--input", a.vectors_dir,
           "--index", a.index_dir,
           "--generator", "DefaultLuceneDocumentGenerator",
           "--threads", str(a.threads),
           "--impact", "--pretokenized", "--optimize"]
    _run_pyserini_index(cmd)
    info(f"✅ SPLADE impact index at {a.index_dir}")

def cmd_search(a):
    """Single-query search: bm25 | splade | hybrid."""
    from pyserini.search.lucene import LuceneSearcher, LuceneImpactSearcher
    if a.mode in ("splade","hybrid"):
        from sentence_transformers import SparseEncoder
        mk={"provider": a.provider}
        if a.onnx_file: mk["file_name"]=a.onnx_file
        enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)

    def run_bm25(q):
        s=LuceneSearcher(a.bm25_index)
        if a.k1 is not None and a.b is not None:
            s.set_bm25(a.k1, a.b)  # documented BM25 API
        return [(h.docid, h.score) for h in s.search(q, k=a.k)]

    def run_splade(q):
        qemb = enc.encode_query([q])
        dec  = enc.decode(qemb, top_k=None)[0]
        qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
        s=LuceneImpactSearcher(a.splade_index)
        return [(h.docid, h.score) for h in s.search(qstr, k=a.k)]

    if a.mode=="bm25":
        hits=run_bm25(a.query)
    elif a.mode=="splade":
        hits=run_splade(a.query)
    else:
        bm = run_bm25(a.query)
        sp = run_splade(a.query)
        hits = rrf_fuse(bm, sp, k=a.rrf_k, topk=a.k)

    for i,(doc,score) in enumerate(hits,1):
        print(i, doc, f"{score:.4f}")

def _read_topics(tsv_path: Path):
    q = {}
    with tsv_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            qid, query = line.rstrip("\n").split("\t", 1)
            q[qid]=query
    return q

def cmd_search_batch(a):
    """Batch search; writes a TREC run file."""
    from pyserini.search.lucene import LuceneSearcher, LuceneImpactSearcher
    topics = _read_topics(Path(a.topics))
    run = {}

    # Prepare searchers
    bm25=None; splade=None; enc=None
    if a.mode in ("bm25","hybrid"):
        bm25 = LuceneSearcher(a.bm25_index)
        if a.k1 is not None and a.b is not None:
            bm25.set_bm25(a.k1, a.b)  # BM25 params
    if a.mode in ("splade","hybrid"):
        from sentence_transformers import SparseEncoder
        mk={"provider": a.provider}
        if a.onnx_file: mk["file_name"]=a.onnx_file
        enc  = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)
        splade = LuceneImpactSearcher(a.splade_index)

    for qid, qtext in topics.items():
        if a.mode == "bm25":
            hits = bm25.search(qtext, k=a.k)
            run[qid] = [(h.docid, h.score) for h in hits]
        elif a.mode == "splade":
            qemb = enc.encode_query([qtext]); dec=enc.decode(qemb, top_k=None)[0]
            qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
            hits = splade.search(qstr, k=a.k)
            run[qid] = [(h.docid, h.score) for h in hits]
        else:
            bm = bm25.search(qtext, k=a.k_fusion)
            qemb = enc.encode_query([qtext]); dec=enc.decode(qemb, top_k=None)[0]
            qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
            sp = splade.search(qstr, k=a.k_fusion)
            run[qid] = rrf_fuse([(h.docid,h.score) for h in bm],
                                 [(h.docid,h.score) for h in sp],
                                 k=a.rrf_k, topk=a.k)

    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    write_trec_run(run, out, tag=a.tag)
    info(f"✅ wrote run file: {out}")

def cmd_eval(a):
    """Call pyserini.eval.trec_eval to compute metrics like MAP/NDCG@10."""
    require_path(Path(a.qrels), "file"); require_path(Path(a.run), "file")
    # Example: python -m pyserini.eval.trec_eval -c -m ndcg_cut.10 -m map qrels.txt run.trec
    cmd=[sys.executable,"-m","pyserini.eval.trec_eval","-c"]
    for m in a.metric: cmd += ["-m", m]
    cmd += [a.qrels, a.run]
    info(" ".join(cmd))
    subprocess.run(cmd, check=False)

def cmd_tune_bm25(a):
    """Grid-search BM25 (k1,b) using topics+qrels and ndcg_cut.10 (default)."""
    topics = _read_topics(Path(a.topics))
    tmpdir = Path(tempfile.mkdtemp(prefix="bm25tune_"))
    best = (None, None, -1.0)
    for k1 in a.k1_grid:
        for b in a.b_grid:
            # Build run in-memory then write to tmp file
            from pyserini.search.lucene import LuceneSearcher
            s=LuceneSearcher(a.bm25_index); s.set_bm25(k1,b)
            run={}
            for qid,q in topics.items():
                hits=s.search(q, k=a.k)
                run[qid]=[(h.docid,h.score) for h in hits]
            run_path = tmpdir / f"run.k1_{k1:.3f}.b_{b:.3f}.trec"
            write_trec_run(run, run_path, tag=f"bm25_k1{k1}_b{b}")
            # Evaluate ndcg_cut.10 (or any metric list)
            cmd=[sys.executable,"-m","pyserini.eval.trec_eval","-c","-m",a.metric,a.qrels,str(run_path)]
            out=subprocess.run(cmd, capture_output=True, text=True).stdout
            score=None
            for line in out.splitlines():
                parts=line.split()
                if len(parts)>=3 and parts[0]==a.metric and parts[1]=="all":
                    score=float(parts[2]); break
            if score is None: warn(f"Could not parse metric for k1={k1},b={b}")
            else:
                info(f"k1={k1:.2f}, b={b:.2f} → {a.metric}={score:.5f}")
                if score>best[2]: best=(k1,b,score)
    print(f"BEST: k1={best[0]:.3f}, b={best[1]:.3f}, {a.metric}={best[2]:.5f}")

def cmd_train(a):
    """Minimal SPLADE finetuning on triples JSONL (uses GPU if available)."""
    import torch, ujson
    from datasets import IterableDataset
    from sentence_transformers import SparseEncoder
    from sentence_transformers.sparse_encoder.losses import (
        SparseMultipleNegativesRankingLoss, SpladeLoss, FlopsLoss
    )
    from sentence_transformers.sparse_encoder.training import (
        SparseEncoderTrainer, SparseEncoderTrainingArguments
    )

    class Triples(IterableDataset):
        def __iter__(self):
            with Path(a.train_file).open("r", encoding="utf-8") as f:
                for line in f:
                    ex=ujson.loads(line)
                    yield {"query": ex["query"], "pos": ex["positive"], "neg": ex.get("negative","")}

    device="cuda" if torch.cuda.is_available() else "cpu"
    info(f"Loading base model {a.base_model} on {device}")
    model=SparseEncoder(a.base_model, device=device)

    mnrl=SparseMultipleNegativesRankingLoss(model=model)
    sreg=SpladeLoss(model=model)
    flops=FlopsLoss(model=model)

    args=SparseEncoderTrainingArguments(
        output_dir=a.out_dir,
        per_device_train_batch_size=a.batch,
        num_train_epochs=a.epochs,
        learning_rate=a.lr,
        logging_steps=100,
        save_steps=a.save_steps,
        remove_unused_columns=False
    )
    trainer=SparseEncoderTrainer(model=model, args=args, train_dataset=Triples(),
                                 loss=[mnrl,sreg,flops])
    trainer.train()
    model.save_pretrained(a.out_dir)
    info(f"✅ Saved finetuned model to {a.out_dir}")
    info("Tip: re-run `export` with --model-id set to this directory to create optimized ONNX.")

def cmd_bench(a):
    """Micro-benchmark ONNX query encoding latency."""
    from sentence_transformers import SparseEncoder
    texts=[a.query]*a.batch
    mk={"provider": a.provider}
    if a.onnx_file: mk["file_name"]=a.onnx_file
    enc=SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)
    for _ in range(10): enc.encode_query(texts)  # warmup
    l=[]
    for _ in range(a.repeats):
        t0=time.time(); enc.encode_query(texts); l.append(1000*(time.time()-t0))
    l.sort()
    p50=l[len(l)//2]; p95=l[int(0.95*(len(l)-1))]
    print(f"p50={p50:.1f}ms  p95={p95:.1f}ms  (batch={a.batch}, repeats={a.repeats})")

# ---------------------------
# CLI
# ---------------------------

def build_cli():
    p=argparse.ArgumentParser(prog="playbook.py",
        description="SPLADE-v3 (ONNX) + BM25 with Pyserini — unified playbook")
    s=p.add_subparsers(dest="cmd", required=True)

    sp=s.add_parser("export", help="Export SPLADE-v3 to ONNX, optionally optimize/quantize.")
    sp.add_argument("--model-id", default="naver/splade-v3")
    sp.add_argument("--out-dir", default="models/splade-v3")
    sp.add_argument("--optimize", action="store_true")
    sp.add_argument("--quantize", action="store_true")
    sp.set_defaults(func=cmd_export)

    sp=s.add_parser("prepare-bm25", help="Normalize corpus.jsonl -> JsonCollection.")
    sp.add_argument("--corpus", default="data/corpus.jsonl")
    sp.add_argument("--out-dir", default="data/jsonl")
    sp.set_defaults(func=cmd_prepare_bm25)

    sp=s.add_parser("index-bm25", help="Build BM25 index.")
    sp.add_argument("--json-dir", default="data/jsonl")
    sp.add_argument("--index-dir", default="indexes/bm25")
    sp.add_argument("--threads", type=int, default=8)
    sp.set_defaults(func=cmd_index_bm25)

    sp=s.add_parser("encode", help="Encode corpus -> SPLADE JsonVectorCollection with ONNX.")
    sp.add_argument("--corpus", default="data/corpus.jsonl")
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--out-dir", default="data/splade_vectors")
    sp.add_argument("--batch", type=int, default=32)
    sp.add_argument("--quant", type=int, default=100)
    sp.add_argument("--shard-size", type=int, default=100_000)
    sp.set_defaults(func=cmd_encode)

    sp=s.add_parser("index-splade", help="Build SPLADE impact index.")
    sp.add_argument("--vectors-dir", default="data/splade_vectors")
    sp.add_argument("--index-dir", default="indexes/splade_v3_impact")
    sp.add_argument("--threads", type=int, default=16)
    sp.add_argument("--max-clause", type=int, default=4096)
    sp.set_defaults(func=cmd_index_splade)

    sp=s.add_parser("search", help="Single query: bm25 | splade | hybrid (RRF).")
    sp.add_argument("--mode", choices=["bm25","splade","hybrid"], required=True)
    sp.add_argument("--query", required=True)
    sp.add_argument("--k", type=int, default=10)
    sp.add_argument("--bm25-index", default="indexes/bm25")
    sp.add_argument("--splade-index", default="indexes/splade_v3_impact")
    sp.add_argument("--k1", type=float, default=None)
    sp.add_argument("--b", type=float, default=None)
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--quant", type=int, default=100)
    sp.add_argument("--max-terms", type=int, default=3000)
    sp.add_argument("--rrf-k", type=int, default=60)
    sp.set_defaults(func=cmd_search)

    sp=s.add_parser("search-batch", help="Batch search from topics TSV -> TREC run file.")
    sp.add_argument("--mode", choices=["bm25","splade","hybrid"], required=True)
    sp.add_argument("--topics", required=True, help="TSV with qid\\tquery")
    sp.add_argument("--output", required=True, help="Output TREC run path")
    sp.add_argument("--tag", default="Pyserini")
    sp.add_argument("--k", type=int, default=1000)
    sp.add_argument("--k-fusion", type=int, default=1000)
    sp.add_argument("--rrf-k", type=int, default=60)
    sp.add_argument("--bm25-index", default="indexes/bm25")
    sp.add_argument("--splade-index", default="indexes/splade_v3_impact")
    sp.add_argument("--k1", type=float, default=None)
    sp.add_argument("--b", type=float, default=None)
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--quant", type=int, default=100)
    sp.add_argument("--max-terms", type=int, default=3000)
    sp.set_defaults(func=cmd_search_batch)

    sp=s.add_parser("eval", help="Evaluate a run with pyserini.eval.trec_eval.")
    sp.add_argument("--qrels", required=True)
    sp.add_argument("--run", required=True)
    sp.add_argument("--metric", action="append", default=["ndcg_cut.10","map"])
    sp.set_defaults(func=cmd_eval)

    sp=s.add_parser("tune-bm25", help="Grid-search BM25 (k1,b) on topics+qrels.")
    sp.add_argument("--bm25-index", default="indexes/bm25")
    sp.add_argument("--topics", required=True)
    sp.add_argument("--qrels", required=True)
    sp.add_argument("--k", type=int, default=1000)
    sp.add_argument("--metric", default="ndcg_cut.10")
    sp.add_argument("--k1-grid", type=float, nargs="+", default=[0.6,0.9,1.2,1.5])
    sp.add_argument("--b-grid", type=float,  nargs="+", default=[0.2,0.4,0.6,0.8])
    sp.set_defaults(func=cmd_tune_bm25)

    sp=s.add_parser("train", help="(Optional) Finetune SPLADE on triples JSONL.")
    sp.add_argument("--train-file", required=True, help='Lines: {"query","positive","negative"}')
    sp.add_argument("--base-model", default="naver/splade-v3")
    sp.add_argument("--out-dir", default="models/splade-finetuned")
    sp.add_argument("--epochs", type=int, default=1)
    sp.add_argument("--batch",  type=int, default=16)
    sp.add_argument("--lr",     type=float, default=2e-5)
    sp.add_argument("--save-steps", type=int, default=1000)
    sp.set_defaults(func=cmd_train)

    sp=s.add_parser("bench", help="Micro-benchmark ONNX query encoding.")
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--query", default="how to claim solar credits")
    sp.add_argument("--batch", type=int, default=8)
    sp.add_argument("--repeats", type=int, default=50)
    sp.set_defaults(func=cmd_bench)

    return p

def main():
    cli=build_cli()
    args=cli.parse_args()
    args.func(args)

if __name__=="__main__":
    main()
```

---

# `Makefile`

```makefile
# SPLADE-v3 (ONNX, CPU) + BM25 with Pyserini — Makefile

VENV        := .venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip

MODEL_ID    ?= naver/splade-v3
MODEL_DIR   ?= models/splade-v3
ONNX_FILE   ?= onnx/model_qint8.onnx

CORPUS      ?= data/corpus.jsonl
JSON_DIR    ?= data/jsonl
VEC_DIR     ?= data/splade_vectors

BM25_INDEX  ?= indexes/bm25
SPLADE_IDX  ?= indexes/splade_v3_impact

TOPICS      ?= data/topics.tsv
QRELS       ?= data/qrels.txt
RUN         ?= runs/run.trec
TAG         ?= Playbook

Q           ?= solar incentives
K           ?= 10

.PHONY: setup
setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip wheel
	# CPU Torch (serving is ONNX Runtime)
	$(PIP) install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio
	$(PIP) install "sentence-transformers[onnx]>=5.1.0" onnxruntime "pyserini>=1.3.0" ujson tqdm

.PHONY: export
export:
	$(PY) playbook.py export --model-id "$(MODEL_ID)" --out-dir "$(MODEL_DIR)" --optimize --quantize

.PHONY: prepare-bm25
prepare-bm25:
	$(PY) playbook.py prepare-bm25 --corpus "$(CORPUS)" --out-dir "$(JSON_DIR)"

.PHONY: index-bm25
index-bm25:
	$(PY) playbook.py index-bm25 --json-dir "$(JSON_DIR)" --index-dir "$(BM25_INDEX)"

.PHONY: encode
encode:
	$(PY) playbook.py encode --corpus "$(CORPUS)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)" --out-dir "$(VEC_DIR)"

.PHONY: index-splade
index-splade:
	$(PY) playbook.py index-splade --vectors-dir "$(VEC_DIR)" --index-dir "$(SPLADE_IDX)"

.PHONY: search-bm25
search-bm25:
	$(PY) playbook.py search --mode bm25 --query "$(Q)" --k $(K) --bm25-index "$(BM25_INDEX)"

.PHONY: search-splade
search-splade:
	$(PY) playbook.py search --mode splade --query "$(Q)" --k $(K) --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: search-hybrid
search-hybrid:
	$(PY) playbook.py search --mode hybrid --query "$(Q)" --k $(K) --bm25-index "$(BM25_INDEX)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: batch-bm25
batch-bm25:
	$(PY) playbook.py search-batch --mode bm25 --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --bm25-index "$(BM25_INDEX)"

.PHONY: batch-splade
batch-splade:
	$(PY) playbook.py search-batch --mode splade --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: batch-hybrid
batch-hybrid:
	$(PY) playbook.py search-batch --mode hybrid --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --bm25-index "$(BM25_INDEX)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: eval
eval:
	$(PY) playbook.py eval --qrels "$(QRELS)" --run "$(RUN)" --metric ndcg_cut.10 --metric map

.PHONY: tune-bm25
tune-bm25:
	$(PY) playbook.py tune-bm25 --bm25-index "$(BM25_INDEX)" --topics "$(TOPICS)" --qrels "$(QRELS)" --k 1000

.PHONY: train
train:
	$(PY) playbook.py train --train-file data/train.jsonl --base-model "$(MODEL_ID)" --out-dir models/splade-finetuned

.PHONY: clean
clean:
	rm -rf "$(JSON_DIR)" "$(VEC_DIR)" "$(BM25_INDEX)" "$(SPLADE_IDX)" runs
```

---

## How to use (end-to-end)

```bash
# 0) one-time setup (CPU stack + ORT)
make setup

# 1) export SPLADE-v3 to ONNX (optimized + int8)
make export

# 2) prepare corpora for both index types
make prepare-bm25
make encode

# 3) build both indexes
make index-bm25
make index-splade

# 4) interactive searches
make search-bm25  Q="how to claim solar credits"
make search-splade Q="how to claim solar credits"
make search-hybrid Q="how to claim solar credits"

# 5) batch: topics.tsv -> TREC run; evaluate with qrels
# topics.tsv lines: qid<TAB>query
make batch-hybrid TOPICS=data/topics.tsv RUN=runs/hybrid.trec TAG=Hybrid
make eval QRELS=data/qrels.txt RUN=runs/hybrid.trec

# 6) (optional) BM25 tuning
make tune-bm25 TOPICS=data/topics.tsv QRELS=data/qrels.txt

# 7) (optional) finetune SPLADE then re-export & re-index
make train
python playbook.py export --model-id models/splade-finetuned --out-dir models/splade-finetuned --optimize --quantize
python playbook.py encode --corpus data/corpus.jsonl --model-dir models/splade-finetuned --onnx-file onnx/model_qint8.onnx --out-dir data/splade_vectors
make index-splade
```

---

## Practical guidance & notes

* **BM25 parameters.** You can set `k1` and `b` in single/batch modes (we expose them and call `LuceneSearcher.set_bm25(k1,b)`), and we provide a **grid-search** helper that evaluates (default) **ndcg@10** via `pyserini.eval.trec_eval`. ([Hugging Face][1])

* **SPLADE impact indexing.** We generate the same **JsonVectorCollection** + `--impact --pretokenized --optimize` index as upstream prebuilt SPLADE-v3 BEIR indexes — you’re on the well-trodden path. ([Hugging Face][2])

* **ONNX acceleration.** We default to **ONNX Runtime, int8 dynamic quantization** for portability & AMD CPUs. The export and optimization helpers come straight from the Sentence-Transformers docs. ([SentenceTransformers][6])

* **RRF hybrid.** The hybrid mode merges BM25 and SPLADE per query using **Reciprocal Rank Fusion**; this is robust and does not require score normalization. (Pyserini also ships a CLI fusion tool; our implementation mirrors that approach.) ([ws-dl.blogspot.com][7])

* **Long SPLADE queries.** If you ever hit `BooleanQuery$TooManyClauses` (default 1024), lower the quantization (e.g., 50) or raise the limit; we expose `--max-clause` for indexing JVM, and you can set `BooleanQuery.setMaxClauseCount(...)` at runtime in Java stacks. ([lucene.apache.org][5])

* **Incremental updates.** Lucene supports **create-or-append** and segment merges, but in practice, append/update workflows for learned-sparse can get tricky (field consistency, deletes). Many teams build **delta indexes** and swap/merge offline. See Pyserini discussions on appending/merging for context. ([GitHub][8])

* **Licensing.** `naver/splade-v3` is **CC BY-NC-SA 4.0** (non-commercial). Ensure your use fits. (Accept terms on Hugging Face before export.)

---

[1]: https://huggingface.co/spaces/castorini/ONNX-Demo/resolve/55810ac7b04ee669aff8742ec21c59932ac35d3c/pyserini/search/lucene/__main__.py?download=true&utm_source=chatgpt.com "https://huggingface.co/spaces/castorini/ONNX-Demo/..."
[2]: https://huggingface.co/datasets/castorini/prebuilt-indexes-beir/raw/main/lucene-inverted/splade-v3/lucene-inverted.beir-v1.0.0-splade-v3.20250603.168a2d.README.md?utm_source=chatgpt.com "raw"
[3]: https://sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html?utm_source=chatgpt.com "SparseEncoder — Sentence Transformers documentation"
[4]: https://github.com/castorini/pyserini/issues/2329?utm_source=chatgpt.com "bug in trec_eval introduced by #2274 · Issue #2329"
[5]: https://lucene.apache.org/core/8_1_0/core/org/apache/lucene/search/BooleanQuery.html?utm_source=chatgpt.com "BooleanQuery (Lucene 8.1.0 API)"
[6]: https://sbert.net/docs/sentence_transformer/usage/efficiency.html?utm_source=chatgpt.com "Speeding up Inference"
[7]: https://ws-dl.blogspot.com/2022/02/2022-02-16-pyserini-information.html?utm_source=chatgpt.com "2022-02-16: Pyserini: an Information Retrieval Framework"
[8]: https://github.com/castorini/pyserini/issues/1964?utm_source=chatgpt.com "Updating Index in Pyserini Without Full Reindexing when ..."



# APPENDIX - BACKGROUND REFERENCE MATERIAL ONLY, CODEINTEL RELEVANT INSTRUCTION SET ABOVE #


Great call—on **AMD** and for maximum portability, go **ONNX Runtime**. Below is a clean, end-to-end “ONNX-first” playbook for **SPLADE-v3** with Pyserini that you can drop into your repo. It:

* exports/optimizes/quantizes SPLADE-v3 to ONNX (CPU),
* encodes your corpus with the ONNX backend,
* builds a Lucene **impact** index,
* serves regular search (SPLADE, BM25, or Hybrid/RRF) with **fast CPU query encoding** via ONNX.

I’ve pinned the API calls against the Sentence-Transformers docs (SparseEncoder, ONNX backend, and the official export helpers) and Pyserini’s impact indexing recipe. ([Sentence Transformers][1])

> Heads-up: `naver/splade-v3` is under **CC BY-NC-SA 4.0** and gated on the Hub (accept terms before download). ([Hugging Face][2])

---

# Repo layout

```
splade-onnx-amd/
├─ scripts/
│  ├─ 00_setup_env.sh
│  ├─ 10_export_onnx.py
│  ├─ 20_encode_corpus_onnx.py
│  ├─ 30_build_impact_index.sh
│  ├─ 40_search.py                  # splade | bm25 | hybrid (RRF), ONNX query encoding
│  └─ 50_bench_encode.py            # tiny p50/p95 encoder benchmark (optional)
├─ data/
│  ├─ corpus.jsonl                  # {"id": "...", "contents" | "text": "..."} per line
│  └─ splade_vectors/               # JsonVectorCollection shards
├─ indexes/
│  ├─ bm25/
│  └─ splade_v3_impact/
└─ models/
   └─ splade-v3/                    # ONNX artifacts saved here
```

---

# 0) Environment (ONNX-first)

**scripts/00_setup_env.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

PY=${PY:-python3.11}
command -v "$PY" >/dev/null 2>&1 || PY=python3
$PY -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel

# CPU-only Torch is fine for export/compat (serving will use ONNX Runtime)
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio

# Sentence-Transformers with ONNX extras + ONNX Runtime + Pyserini
pip install "sentence-transformers[onnx]>=5.1.0" \
           "onnxruntime>=1.18.0" \
           "optimum>=1.21.0" \
           "pyserini>=1.3.0" \
           "ujson>=5.8" "tqdm>=4.66"

# Java (for Pyserini/Anserini indexing)
if ! command -v java >/dev/null 2>&1; then
  echo "Install Java (JDK 21) for Lucene indexing." >&2; exit 1
fi
java -version

# Sensible CPU threading defaults for ORT
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-8}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-8}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-8}

echo "✅ ONNX-first env ready."
```

Why this stack? Sentence-Transformers supports **ONNX** as a first-class backend (set `backend="onnx"`), and exposes **export/optimize/quantize** helpers you’ll use below. Pyserini handles Lucene indexing/search (BM25 + learned-sparse). ([Sentence Transformers][3])

---

# 1) Export, optimize & quantize SPLADE-v3 → ONNX (portable CPU)

**scripts/10_export_onnx.py**

```python
import os
from sentence_transformers import SparseEncoder
from sentence_transformers import export_optimized_onnx_model, export_dynamic_quantized_onnx_model

MODEL_ID = os.environ.get("MODEL_ID", "naver/splade-v3")     # accept terms on HF first
SAVE_DIR = os.environ.get("SAVE_DIR", "models/splade-v3")    # local directory to write files

# 1) Load with ONNX backend; auto-exports if missing
enc = SparseEncoder(MODEL_ID, backend="onnx")
enc.save_pretrained(SAVE_DIR)  # persist baseline onnx (onnx/model.onnx)
print(f"Saved base ONNX under {SAVE_DIR}")

# 2) Optimize with Optimum (O3 = fusions + fast GELU)
export_optimized_onnx_model(
    model=enc, optimization_config="O3",
    model_name_or_path=SAVE_DIR, push_to_hub=False, create_pr=False
)
print("Saved optimized ONNX (onnx/model_O3.onnx)")

# 3) Dynamic int8 quantization (choose a portable target; AMD-safe: avx2)
export_dynamic_quantized_onnx_model(
    model=enc, quantization_config="avx2",
    model_name_or_path=SAVE_DIR, push_to_hub=False, create_pr=False,
    file_suffix="qint8_avx2"
)
print("Saved quantized ONNX (onnx/model_qint8_avx2.onnx)")
```

* Use `backend="onnx"` to run/export ONNX; **optimize** via `export_optimized_onnx_model(..., "O3")`; **quantize** via `export_dynamic_quantized_onnx_model(..., "avx2" | "arm64" | "avx512" | "avx512_vnni")`. For **AMD/portable**, pick **`"avx2"`**. ([Sentence Transformers][3])

> Tip: If you later deploy on Intel servers with AVX-512 VNNI, also export a `qint8_avx512_vnni` variant and pick it at runtime via `model_kwargs={"file_name": "..._avx512_vnni.onnx"}`. ([Sentence Transformers][3])

---

# 2) Encode your corpus with ONNX (→ JsonVectorCollection)

Create `data/corpus.jsonl` with one doc per line:

```json
{"id":"d1","contents":"Solar panels convert sunlight into electricity..."}
{"id":"d2","text":"Tax credits and incentives can reduce the cost of solar."}
```

**scripts/20_encode_corpus_onnx.py**

```python
import os, ujson
from pathlib import Path
from tqdm import tqdm
from sentence_transformers import SparseEncoder

SRC = Path("data/corpus.jsonl")
OUT = Path("data/splade_vectors"); OUT.mkdir(parents=True, exist_ok=True)

MODEL_DIR = os.environ.get("MODEL_DIR", "models/splade-v3")
ONNX_FILE = os.environ.get("ONNX_FILE", "onnx/model_qint8_avx2.onnx")  # best portable default
QUANT = int(os.environ.get("QUANT", "100"))  # standard impact quantization

# Load accelerated encoder; force CPUExecutionProvider and our quantized artifact
enc = SparseEncoder(
    MODEL_DIR,
    backend="onnx",
    model_kwargs={"provider": "CPUExecutionProvider", "file_name": ONNX_FILE}
)

def to_impact(decoded, q=100):
    out = {}
    for tok, w in decoded:
        if w > 0:
            iw = int(round(w * q))
            if iw > 0: out[tok] = iw
    return out

shard_size, shard_i, n = 100_000, 0, 0
writer = None
def open_writer(i): return (OUT / f"part-{i:05d}.jsonl").open("w", encoding="utf-8")

with SRC.open("r", encoding="utf-8") as f:
    for line in tqdm(f, desc="Encoding docs (ONNX)"):
        obj = ujson.loads(line)
        docid = str(obj["id"])
        text  = obj.get("contents") or obj.get("text") or ""

        emb = enc.encode_document([text])
        decoded = enc.decode(emb, top_k=None)[0]     # [(token, score), ...]
        rec = {"id": docid, "contents": "", "vector": to_impact(decoded, QUANT)}

        if writer is None: writer = open_writer(shard_i)
        writer.write(ujson.dumps(rec) + "\n")
        n += 1
        if n % shard_size == 0:
            writer.close(); shard_i += 1; writer = open_writer(shard_i)
if writer: writer.close()
print(f"✅ wrote {n} vectors to {OUT}")
```

* We intentionally write **JsonVectorCollection** records `{id, contents:"", vector:{token:int_weight}}`, which is exactly what Pyserini’s learned-sparse “impact” indexer expects. ([Hugging Face][4])
* Using `SparseEncoder(..., backend="onnx")` is the **supported** way to run/query with ONNX; you can select files/providers via `model_kwargs`. ([Sentence Transformers][1])

---

# 3) Build the Lucene **impact** index (SPLADE)

**scripts/30_build_impact_index.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate

# Optional: allow longer expanded queries
export JAVA_TOOL_OPTIONS="-Dorg.apache.lucene.maxClauseCount=4096"

python -m pyserini.index.lucene \
  --collection JsonVectorCollection \
  --input data/splade_vectors \
  --index indexes/splade_v3_impact \
  --generator DefaultLuceneDocumentGenerator \
  --threads 16 \
  --impact --pretokenized --optimize

echo "✅ SPLADE impact index at indexes/splade_v3_impact"
```

This is the **canonical** recipe used for the prebuilt SPLADE-v3 BEIR Lucene indexes (`JsonVectorCollection` + `--impact --pretokenized --optimize`). ([Hugging Face][4])

> If you encounter `BooleanQuery$TooManyClauses` on very long expanded queries, raise `maxClauseCount` (as above) or lower `QUANT` in encoding. Lucene exposes `BooleanQuery.setMaxClauseCount` for this knob. ([Apache Lucene][5])

---

# 4) BM25 index (optional, for hybrid)

```bash
python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input data/jsonl \
  --index indexes/bm25 \
  --generator DefaultLuceneDocumentGenerator \
  --threads 8 \
  --storePositions --storeDocvectors --storeRaw
```

(Use if you want hybrid BM25+SPLADE; otherwise skip.) Pyserini’s `LuceneSearcher` serves BM25. ([PyPI][6])

---

# 5) Search (SPLADE/BM25/Hybrid) with ONNX query encoding

**scripts/40_search.py**

```python
import os, argparse, torch
from pyserini.search.lucene import LuceneSearcher, LuceneImpactSearcher
from sentence_transformers import SparseEncoder

def pseudo_bow_string(decoded, q=100, max_terms=3000):
    # Repeat tokens proportional to (integer) impacts — impact-query convention
    toks = []
    for tok, w in decoded:
        if w <= 0: continue
        iw = int(round(w * q))
        if iw > 0: toks.extend([tok]*iw)
        if len(toks) >= max_terms:
            break
    return " ".join(toks)

def run_splade(index, query, model_dir, onnx_file, quant=100, provider="CPUExecutionProvider"):
    enc = SparseEncoder(model_dir, backend="onnx",
                        model_kwargs={"provider": provider, "file_name": onnx_file})
    # Encode ONNX on CPU
    qemb = enc.encode_query([query])
    decoded = enc.decode(qemb, top_k=None)[0]
    qstr = pseudo_bow_string(decoded, q=quant)
    searcher = LuceneImpactSearcher(index)
    return [(h.docid, h.score) for h in searcher.search(qstr, k=10)]

def run_bm25(index, query):
    s = LuceneSearcher(index)
    return [(h.docid, h.score) for h in s.search(query, k=10)]

def rrf_fuse(bm25_hits, splade_hits, k=60, topk=10):
    scores = {}
    for run in (bm25_hits, splade_hits):
        for rank, (docid, _) in enumerate(run, 1):
            scores[docid] = scores.get(docid, 0.0) + 1.0/(k+rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:topk]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["splade","bm25","hybrid"], required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--splade_index", default="indexes/splade_v3_impact")
    ap.add_argument("--bm25_index", default="indexes/bm25")
    ap.add_argument("--model_dir", default="models/splade-v3")
    ap.add_argument("--onnx_file", default="onnx/model_qint8_avx2.onnx")
    ap.add_argument("--quant", type=int, default=100)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    if args.mode == "bm25":
        out = run_bm25(args.bm25_index, args.query)
    elif args.mode == "splade":
        out = run_splade(args.splade_index, args.query, args.model_dir, args.onnx_file, args.quant, args.provider)
    else:
        bm25 = run_bm25(args.bm25_index, args.query)
        spla = run_splade(args.splade_index, args.query, args.model_dir, args.onnx_file, args.quant, args.provider)
        out = rrf_fuse(bm25, spla, k=60, topk=10)

    for i, (docid, score) in enumerate(out, 1):
        print(i, docid, f"{score:.4f}")
```

* **Query encoding** runs with `SparseEncoder(..., backend="onnx")` and your quantized ONNX file selected via `model_kwargs={"file_name": ...}`; you can choose execution **provider** (`"CPUExecutionProvider"`). ST documents both parameters. ([Sentence Transformers][1])
* Searching uses Pyserini’s **LuceneImpactSearcher** (SPLADE) and **LuceneSearcher** (BM25). The hybrid uses **RRF** (simple and robust). ([PyPI][6])

---

# 6) (Optional) Quick encoder micro-benchmark

**scripts/50_bench_encode.py**

```python
import time, statistics as st
from sentence_transformers import SparseEncoder

texts = ["how to claim solar credits"]*256
enc = SparseEncoder("models/splade-v3", backend="onnx",
                    model_kwargs={"provider":"CPUExecutionProvider",
                                  "file_name":"onnx/model_qint8_avx2.onnx"})
latencies=[]
for _ in range(25):  # warmup
    enc.encode_query(texts[:8])
for _ in range(50):
    t0=time.time(); enc.encode_query(texts[:8]); latencies.append((time.time()-t0)*1000)
print("p50=%.1fms p95=%.1fms" % (st.median(latencies), st.quantiles(latencies, n=20)[18]))
```

This measures the ONNX path on your AMD CPU. (ST’s docs also show an ONNX/OpenVINO benchmark section if you want apples-to-apples with PyTorch.) ([Sentence Transformers][3])

---

# How to run it

```bash
# 0) env
bash scripts/00_setup_env.sh

# 1) export/optimize/quantize SPLADE-v3 to ONNX (accept model terms on HF first)
python scripts/10_export_onnx.py

# 2) encode corpus (ONNX)
python scripts/20_encode_corpus_onnx.py

# 3) build indexes
bash scripts/30_build_impact_index.sh
# (optional) BM25 if you want hybrid
# python -m pyserini.index.lucene ... (see section 4)

# 4) search (all on CPU)
python scripts/40_search.py --mode splade --query "renewable energy incentives"
python scripts/40_search.py --mode bm25  --query "renewable energy incentives"
python scripts/40_search.py --mode hybrid --query "renewable energy incentives"

# 5) (optional) check encoder latency on your AMD CPU
python scripts/50_bench_encode.py
```

---

## Practical notes & choices (AMD + portability)

* **Why ONNX (and not OpenVINO) here?**
  Sentence-Transformers explicitly supports both ONNX and OpenVINO backends. For **non-Intel / mixed fleets**, ONNX is the portable choice; you can export once and run anywhere with ONNX Runtime, selecting an appropriate **dynamic quantization** config like `avx2`. ([Sentence Transformers][3])

* **Optimization & quantization levels**
  Use **O3** optimization and **int8 dynamic quantization**. Valid quantization configs are `"arm64"`, `"avx2"`, `"avx512"`, `"avx512_vnni"`. For AMD + portability, default to **`"avx2"`**; export a second artifact for Intel VNNI if needed. ([Sentence Transformers][3])

* **Search stays CPU**
  Only the SPLADE **encoder** benefits from ONNX acceleration; Lucene matching/ranking is CPU either way. ([PyPI][6])

* **Indexing flags**
  Stick to `JsonVectorCollection` + `--impact --pretokenized --optimize`; this is exactly how Castorini publish SPLADE-v3 impact indexes for BEIR. ([Hugging Face][4])

* **Long queries**
  SPLADE expands queries; if you see `TooManyClauses`, either lower `--quant` (e.g., 50) or raise `maxClauseCount` (we set 4096 via `JAVA_TOOL_OPTIONS`). Lucene exposes `BooleanQuery.setMaxClauseCount`. ([Apache Lucene][5])

* **Model license**
  `naver/splade-v3` is **cc-by-nc-sa-4.0**; ensure your usage fits. ([Hugging Face][2])

---

## API receipts (where these calls come from)

* **SparseEncoder** supports `backend="onnx"` plus `model_kwargs` such as `provider` and `file_name`; if the ONNX isn’t present, ST exports it for you. ([Sentence Transformers][1])
* **Export helpers** used above are officially documented:
  `export_optimized_onnx_model(...)` and `export_dynamic_quantized_onnx_model(...)`. ([Sentence Transformers][3])
* **Pyserini impact indexing** recipe (`--impact --pretokenized`) for SPLADE-v3 is published with their prebuilt BEIR indexes. ([Hugging Face][4])

---

If you want, I can also fold these into a single `playbook.py` with subcommands (`export`, `encode`, `index`, `search`, `bench`) and a tiny `Makefile`.

[1]: https://sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html "SparseEncoder — Sentence Transformers  documentation"
[2]: https://huggingface.co/naver/splade-v3 "naver/splade-v3 · Hugging Face"
[3]: https://sbert.net/docs/sentence_transformer/usage/efficiency.html "Speeding up Inference — Sentence Transformers  documentation"
[4]: https://huggingface.co/datasets/castorini/prebuilt-indexes-beir/blob/main/lucene-inverted/splade-v3/lucene-inverted.beir-v1.0.0-splade-v3.20250603.168a2d.README.md?utm_source=chatgpt.com "BEIR (v1.0.0): SPLADE-v3 Indexes - lucene-inverted"
[5]: https://lucene.apache.org/core/8_1_0/core/org/apache/lucene/search/BooleanQuery.html?utm_source=chatgpt.com "BooleanQuery (Lucene 8.1.0 API)"
[6]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"

Here’s a copy-pasteable “playbook” your team can drop into a repo to run **BM25** and **SPLADE-v3** end-to-end with **Pyserini**, with optional **GPU/CPU** for training and inference. It includes install scripts, indexing, query-time code (BM25, SPLADE, and hybrid RRF), and an optional fine-tuning entrypoint using Sentence-Transformers’ **SparseEncoder** stack.

I’ve pinned the key interfaces/flags against current docs and examples (Pyserini 1.3.0; Java 21; ST 4.x with SparseEncoder + ONNX/OpenVINO acceleration). ([Pyserini][1])
The SPLADE-v3 model is gated on the Hub (must accept terms before download). ([Hugging Face][2])
Pyserini impact indexing for learned-sparse uses **JsonVectorCollection** + `--impact --pretokenized --optimize` (same invocation used to ship their prebuilt SPLADE-v3 BEIR indexes). ([Hugging Face][3])
Query-time SPLADE uses `LuceneImpactSearcher` with a `SpladeQueryEncoder`. ([Hugging Face][4])
ST’s SparseEncoder supports training, **SpladeLoss/FlopsLoss**, multi-GPU/CPU encoding, and ONNX/OpenVINO backends for fast **CPU** paths. ([Sentence Transformers][5])

---

# Repository layout

```
spladev3-pyserini-playbook/
├─ scripts/
│  ├─ 00_setup_env.sh
│  ├─ 01_download_model.py
│  ├─ 02_prepare_bm25_jsons.py
│  ├─ 03_encode_corpus_splade.py
│  ├─ 04_index_bm25.sh
│  ├─ 05_index_splade_impact.sh
│  ├─ 06_search.py                 # bm25 | splade | hybrid (RRF)
│  └─ 07_train_splade.py           # optional fine-tuning (GPU/CPU auto)
├─ data/
│  ├─ corpus.jsonl                 # {"id": "...", "contents" | "text": "..."} per line
│  ├─ jsonl/                       # normalized per-doc JSON files for BM25
│  └─ splade_vectors/              # shards with {"id","contents":"","vector":{tok:int,...}}
├─ indexes/
│  ├─ bm25/
│  └─ splade_v3_impact/
└─ models/
   └─ naver/splade-v3/             # local snapshot (optional)
```

---

# 0) Environment & prerequisites

**scripts/00_setup_env.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Create a local venv
PY=${PY:-python3.11}
command -v "$PY" >/dev/null 2>&1 || PY=python3
$PY -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel

# Install Torch for CPU or CUDA (12.1 wheels by default; change if needed)
if command -v nvidia-smi >/dev/null 2>&1; then
  pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio
else
  pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio
fi

# Core libs
pip install "pyserini>=1.3.0" \
           "sentence-transformers[train]>=4.1.0" \
           "huggingface_hub>=0.23" "datasets>=2.19.0" \
           "ujson>=5.8" "tqdm>=4.66"

# Pyserini runs on Python 3.11 + Java 21 (via Anserini/Lucene)
if ! command -v java >/dev/null 2>&1; then
  echo "Java 21 (JDK) is required by Pyserini/Anserini. Install it and set JAVA_HOME." 1>&2
  exit 1
fi
java -version
echo "✅ Environment ready."
```

Why: Pyserini 1.3.0 (Nov 1 2025) targets **Python 3.11** and **Java 21**; `pip install pyserini` pulls PyTorch/Transformers/ONNX Runtime automatically. ([Pyserini][1])

---

# 1) Model download (gated checkpoint)

**scripts/01_download_model.py**

```python
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="naver/splade-v3",
    local_dir="models/naver/splade-v3",
    local_dir_use_symlinks=False
)
print("Downloaded: models/naver/splade-v3")
```

> Note: you must be logged in and accept `naver/splade-v3` terms to access files. (`huggingface-cli login`). ([Hugging Face][2])

---

# 2) Prepare BM25 input (JsonCollection)

Input: `data/corpus.jsonl` lines like:

```json
{"id":"doc1","contents":"Text of doc1..."}
{"id":"doc2","text":"Text of doc2..."}   // "text" also accepted; mapped to contents
```

**scripts/02_prepare_bm25_jsons.py**

```python
import ujson, os
from pathlib import Path

src = Path("data/corpus.jsonl")
out = Path("data/jsonl"); out.mkdir(parents=True, exist_ok=True)

with src.open("r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        obj = ujson.loads(line)
        docid = str(obj["id"])
        contents = obj.get("contents") or obj.get("text") or ""
        with (out / f"{docid}.json").open("w", encoding="utf-8") as w:
            ujson.dump({"id": docid, "contents": contents}, w)
        if i % 10000 == 0:
            print(f"wrote {i} docs")
print("✅ JsonCollection at data/jsonl/")
```

---

# 3) Encode corpus with SPLADE-v3 (Sentence-Transformers path)

This generates Pyserini’s **JsonVectorCollection** shards with an integer-quantized `vector` field (token→impact), required for **impact indexing**. Use GPU if available; otherwise CPU. ST’s `SparseEncoder` exposes `encode_document` / `encode_query` and `decode` to get (token, weight). ([Sentence Transformers][6])

**scripts/03_encode_corpus_splade.py**

```python
import os, ujson, torch
from pathlib import Path
from tqdm import tqdm
from sentence_transformers import SparseEncoder

JSONL_IN = Path("data/corpus.jsonl")
OUT_DIR  = Path("data/splade_vectors"); OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = os.environ.get("SPLADE_MODEL", "naver/splade-v3")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH = int(os.environ.get("BATCH", "32"))
QUANT = int(os.environ.get("QUANT", "100"))  # common for impact indexes

print(f"Loading SparseEncoder({MODEL_NAME}) on {DEVICE}")
enc = SparseEncoder(MODEL_NAME, device=DEVICE)

shard_idx, shard_size, n = 0, 100_000, 0
writer = None
def open_writer(i): return (OUT_DIR / f"part-{i:05d}.jsonl").open("w", encoding="utf-8")

with JSONL_IN.open("r", encoding="utf-8") as f:
    for line in tqdm(f, desc="encode docs"):
        obj = ujson.loads(line)
        docid = str(obj["id"])
        text  = obj.get("contents") or obj.get("text") or ""

        # 1) embed, 2) decode tokens+weights, 3) quantize to ints (impact)
        emb = enc.encode_document([text])
        tok_weights = enc.decode(emb, top_k=None)[0]

        vector = {}
        for tok, w in tok_weights:
            if w > 0:
                q = int(round(w * QUANT))
                if q > 0: vector[tok] = q

        rec = {"id": docid, "contents": "", "vector": vector}

        if writer is None: writer = open_writer(shard_idx)
        writer.write(ujson.dumps(rec) + "\n")
        n += 1
        if n % shard_size == 0:
            writer.close(); shard_idx += 1; writer = open_writer(shard_idx)
if writer is not None: writer.close()
print(f"✅ Wrote {n} SPLADE vectors to {OUT_DIR}")
```

> To speed up **CPU** encoding later, you can export ONNX or OpenVINO backends (SparseEncoder supports both). ([Sentence Transformers][7])

---

# 4) Build the Lucene indexes

### 4a) BM25 (standard positional index)

**scripts/04_index_bm25.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input data/jsonl \
  --index indexes/bm25 \
  --generator DefaultLuceneDocumentGenerator \
  --threads 8 \
  --storePositions --storeDocvectors --storeRaw
echo "✅ BM25 index: indexes/bm25"
```

BM25 indexing via `JsonCollection` and `LuceneSearcher` is the canonical Pyserini path. ([PyPI][8])

### 4b) SPLADE impact index (learned-sparse)

**scripts/05_index_splade_impact.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
python -m pyserini.index.lucene \
  --collection JsonVectorCollection \
  --input data/splade_vectors \
  --index indexes/splade_v3_impact \
  --generator DefaultLuceneDocumentGenerator \
  --threads 16 \
  --impact --pretokenized --optimize
echo "✅ SPLADE impact index: indexes/splade_v3_impact"
```

These flags are exactly what Castorini uses to ship prebuilt SPLADE-v3 Lucene indexes (impact, pretokenized, optimize). ([Hugging Face][3])

---

# 5) Search (BM25, SPLADE, Hybrid/RRF) with device auto-selection

**scripts/06_search.py**

```python
import argparse, torch
from pyserini.search.lucene import LuceneSearcher, LuceneImpactSearcher
from pyserini.encode import SpladeQueryEncoder

def run_bm25(index_dir, query, k):
    s = LuceneSearcher(index_dir)
    # Tune if desired:
    # s.set_bm25(k1=0.9, b=0.4)
    hits = s.search(query, k=k)
    return [(h.docid, h.score) for h in hits]

def run_splade(index_dir, query, k, model):
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    qenc = SpladeQueryEncoder(model, device=device)
    s = LuceneImpactSearcher(index_dir)
    hits = s.search(qenc.encode(query), k=k)
    return [(h.docid, h.score) for h in hits]

def rrf_fuse(runs, k=60, topk=10):
    scores = {}
    for run in runs:
        for rank, h in enumerate(run, start=1):
            docid = h[0] if isinstance(h, tuple) else h.docid
            scores[docid] = scores.get(docid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:topk]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["bm25","splade","hybrid"], required=True)
    ap.add_argument("--bm25_index", default="indexes/bm25")
    ap.add_argument("--splade_index", default="indexes/splade_v3_impact")
    ap.add_argument("--model", default="naver/splade-v3")
    ap.add_argument("--query", required=True)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    if args.mode == "bm25":
        out = run_bm25(args.bm25_index, args.query, args.k)
        for i, (d, s) in enumerate(out, 1): print(i, d, s)
    elif args.mode == "splade":
        out = run_splade(args.splade_index, args.query, args.k, args.model)
        for i, (d, s) in enumerate(out, 1): print(i, d, s)
    else:
        bm25 = run_bm25(args.bm25_index, args.query, 100)
        spla = run_splade(args.splade_index, args.query, 100, args.model)
        fused = rrf_fuse([bm25, spla], k=60, topk=args.k)
        for i, (d, s) in enumerate(fused, 1): print(i, d, s)
```

* `LuceneSearcher` provides BM25; `LuceneImpactSearcher` + `SpladeQueryEncoder` handles SPLADE queries. ([PyPI][8])
* The hybrid (**RRF**) merger used here mirrors Pyserini’s `pyserini.fusion` CLI. If you need CLI fusion for batch runs:
  `python -m pyserini.fusion --runs run.bm25.trec run.splade.trec --k 60 --output run.hybrid.rrf.trec` ([Castorini][9])

---

# 6) Optional: Fine-tune SPLADE (GPU preferred; CPU works)

Minimal trainer for triples (`data/train.jsonl` with `{"query","positive","negative"}` per line) using ST **SparseEncoder** with **SparseMultipleNegativesRankingLoss** + **SpladeLoss** + **FlopsLoss**. These are the official sparse encoder training components. ([Sentence Transformers][10])

**scripts/07_train_splade.py**

```python
import os, ujson, torch
from pathlib import Path
from datasets import IterableDataset
from sentence_transformers import SparseEncoder
from sentence_transformers.sparse_encoder.losses import (
    SparseMultipleNegativesRankingLoss, SpladeLoss, FlopsLoss
)
from sentence_transformers.sparse_encoder.training import (
    SparseEncoderTrainer, SparseEncoderTrainingArguments
)
from sentence_transformers.sparse_encoder.callbacks import (
    SpladeRegularizerWeightSchedulerCallback
)

TRAIN = Path("data/train.jsonl")
MODEL_IN  = os.environ.get("BASE_MODEL", "naver/splade-v3")
MODEL_OUT = os.environ.get("OUT_DIR", "models/splade-finetuned")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
EPOCHS = int(os.environ.get("EPOCHS", "1"))
BATCH  = int(os.environ.get("BATCH", "16"))

class Triples(IterableDataset):
    def __iter__(self):
        with TRAIN.open("r", encoding="utf-8") as f:
            for line in f:
                ex = ujson.loads(line)
                yield {"query": ex["query"], "pos": ex["positive"], "neg": ex.get("negative", "")}

print(f"Loading SparseEncoder {MODEL_IN} on {DEVICE}")
model = SparseEncoder(MODEL_IN, device=DEVICE)
train_ds = Triples()

# Main contrastive loss + SPLADE regularization + FLOPs penalty
mnrl  = SparseMultipleNegativesRankingLoss(model=model)
sreg  = SpladeLoss(model=model)
flops = FlopsLoss(model=model)

args = SparseEncoderTrainingArguments(
    output_dir=MODEL_OUT,
    per_device_train_batch_size=BATCH,
    num_train_epochs=EPOCHS,
    learning_rate=2e-5,
    logging_steps=100,
    save_steps=1000,
    remove_unused_columns=False
)

trainer = SparseEncoderTrainer(
    model=model, args=args, train_dataset=train_ds,
    loss=[mnrl, sreg, flops],
    callbacks=[SpladeRegularizerWeightSchedulerCallback(sreg)]
)
trainer.train()
model.save_pretrained(MODEL_OUT)
print(f"✅ Saved finetuned model to {MODEL_OUT}")
```

* `SparseEncoderTrainer` / `SparseEncoderTrainingArguments` are the ST training loop for sparse encoders. ([Sentence Transformers][11])
* For faster **CPU** inference later, export ONNX/OpenVINO backends (SparseEncoder supports both, with export helpers/flags). ([Sentence Transformers][7])

---

# 7) Make it runnable

After placing the scripts, run:

```bash
# 0) setup
bash scripts/00_setup_env.sh

# (optional) login & accept model terms, then download
python scripts/01_download_model.py

# 1) normalize for BM25
python scripts/02_prepare_bm25_jsons.py

# 2) encode SPLADE (auto GPU/CPU)
python scripts/03_encode_corpus_splade.py

# 3) build indexes
bash scripts/04_index_bm25.sh
bash scripts/05_index_splade_impact.sh

# 4) search
python scripts/06_search.py --mode bm25   --query "solar incentives"
python scripts/06_search.py --mode splade --query "solar incentives"
python scripts/06_search.py --mode hybrid --query "solar incentives"

# 5) (optional) finetune, then re-encode + reindex SPLADE
python scripts/07_train_splade.py
SPLADE_MODEL=models/splade-finetuned python scripts/03_encode_corpus_splade.py
bash scripts/05_index_splade_impact.sh
```

---

## Operational guidance (quick, practical)

* **BM25 vs SPLADE**: BM25 uses `LuceneSearcher` over a standard positional index; SPLADE uses an **impact** index (integer quantized term weights) searched with `LuceneImpactSearcher`. Both are CPU-served; only the SPLADE **encoder** benefits from GPU. ([PyPI][8])
* **Hybrid**: RRF fusion of BM25 and SPLADE is simple and robust; Pyserini ships a `pyserini.fusion` CLI for batch runs. ([Castorini][9])
* **Incremental updates**: For learned-sparse (impact) indexes, the common strategy is to **encode changed docs to new shards** and **re-index** those shards, then (operationally) swap/merge indexes offline. Discussion threads cover appending/merging and caveats (field-type consistency etc.). (Lucene supports add/update/delete; Pyserini workflows generally rebuild shards for cleanliness.) ([GitHub][12])
* **Performance (CPU)**: consider exporting SparseEncoder to **ONNX/OpenVINO** for CPU acceleration; ST 4.1.0+ documents both backends and provides optimization helpers. ([Sentence Transformers][7])
* **Versions/reqs**: Pyserini 1.3.0 (Nov 1 2025) and Java 21; installation notes and “How do I index/search?” live in the project README. ([Pyserini][1])
* **Model card**: `naver/splade-v3` reports MS MARCO/BEIR metrics and usage notes; remember it’s gated. ([Hugging Face][13])

---

## Minimal test corpus (optional)

Drop this into `data/corpus.jsonl` to smoke-test end-to-end:

```json
{"id":"d1","contents":"Solar panels convert sunlight into electricity using photovoltaic cells."}
{"id":"d2","contents":"Tax credits and incentives can reduce the cost of installing solar energy systems."}
{"id":"d3","contents":"Wind turbines generate power by harnessing kinetic energy from the wind."}
```

Then run the indexing and the three search modes; you should see BM25, SPLADE, and hybrid return sensible top docs for queries like “solar incentives”.

---

## Why this playbook is future-proof

* It stays on **Pyserini’s native surface area** (LuceneSearcher/LuceneImpactSearcher; CLI indexers) that are stable across releases. ([Pyserini][1])
* SPLADE vectors are produced with **Sentence-Transformers’ SparseEncoder** (official implementation and training APIs, with documented decode and speed-up backends). ([Sentence Transformers][14])
* The SPLADE impact indexing flags match the **same commands** used for Castorini’s prebuilt SPLADE-v3 BEIR indexes. ([Hugging Face][3])

If you want, I can turn this into a single `Makefile`/`uv` project or wire a single CLI (`playbook.py`) that exposes subcommands (`index-bm25`, `index-splade`, `search`, `train`, `reindex`) and CI smoke tests.

[1]: https://pyserini.io/ "GitHub - castorini/pyserini: Pyserini is a Python toolkit for reproducible information retrieval research with sparse and dense representations."
[2]: https://huggingface.co/naver/splade-v3/tree/main?utm_source=chatgpt.com "naver/splade-v3 at main"
[3]: https://huggingface.co/datasets/castorini/prebuilt-indexes-beir/raw/main/lucene-inverted/splade-v3/lucene-inverted.beir-v1.0.0-splade-v3.20250603.168a2d.README.md?utm_source=chatgpt.com "raw"
[4]: https://huggingface.co/spaces/castorini/ONNX-Demo/blob/f77c5c674639ab1684cf5d8e248d344ff1d95e25/pyserini/search/__init__.py?utm_source=chatgpt.com "pyserini/search/__init__.py · castorini/ONNX-Demo ..."
[5]: https://sbert.net/docs/package_reference/sparse_encoder/index.html?utm_source=chatgpt.com "Sparse Encoder — Sentence Transformers documentation"
[6]: https://sbert.net/docs/migration_guide.html?utm_source=chatgpt.com "Migration Guide — Sentence Transformers documentation"
[7]: https://sbert.net/docs/sparse_encoder/usage/efficiency.html?utm_source=chatgpt.com "Speeding up Inference"
[8]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"
[9]: https://castorini.github.io/pyserini/2cr/odqa.html?utm_source=chatgpt.com "Pyserini Reproductions"
[10]: https://sbert.net/docs/package_reference/sparse_encoder/training_args.html?utm_source=chatgpt.com "Training Arguments"
[11]: https://sbert.net/docs/package_reference/sparse_encoder/trainer.html?utm_source=chatgpt.com "Trainer — Sentence Transformers documentation"
[12]: https://github.com/castorini/pyserini/discussions/1884?utm_source=chatgpt.com "merge a large index with small index \ adding ..."
[13]: https://huggingface.co/naver/splade-v3?utm_source=chatgpt.com "naver/splade-v3"
[14]: https://sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html?utm_source=chatgpt.com "SparseEncoder — Sentence Transformers documentation"


Here’s a practical, opinionated walkthrough of how to configure and run **SPLADE-v3** end-to-end—with clear “CPU vs GPU” choices for (1) initial training/finetuning, (2) indexing/updates, and (3) regular searching.

---

# What SPLADE-v3 is (and why it’s worth it)

**SPLADE-v3** is the latest learned-sparse retriever from Naver Labs Europe. It encodes text into **high-dimensional sparse token-weight vectors** and searches them with a standard inverted index (Lucene/Elastic/OpenSearch). v3 improves over SPLADE++ and BM25 on MS MARCO and BEIR, with reported MRR@10≈40 on MS MARCO dev and strong zero-shot BEIR gains. ([arXiv][1])

A ready-to-use checkpoint lives on the Hub as `naver/splade-v3` (license: **CC BY-NC-SA 4.0**, i.e., non-commercial). You can load it directly via Sentence-Transformers’ **SparseEncoder** API. ([Hugging Face][2])

---

# The pieces you’ll combine

**Model runtime (CPU or GPU):**

* **PyTorch / Sentence-Transformers SparseEncoder** for easy inference and training; supports multi-GPU, ONNX and OpenVINO export for fast **CPU** paths. ([SentenceTransformers][3])
* **Naver’s splade repo** (Hydra configs) for full training/indexing pipelines and export helpers to Anserini/Lucene. ([GitHub][4])

**Search backends (CPU; no GPU required to search):**

* **Lucene/Anserini/Pyserini** (impact indexes for learned-sparse). Pyserini exposes a `LuceneImpactSearcher` and SPLADE query encoder helpers. ([Hugging Face][5])
* **OpenSearch (ML Commons)** or **Elasticsearch 8.17+** for managed sparse search; both now natively support sparse embeddings (upload/serve HF sparse models; ingest-time and query-time inference). ([OpenSearch][6])
* **PyTerrier + PISA** for very fast CPU retrieval (quantized/MaxScore/BMP), with an example SPLADE wrapper. ([GitHub][7])

---

# 1) Initial training / finetuning (GPU *or* CPU)

### Option A — Train with **Naver’s `splade` repo** (Hydra)

The repo provides `train.py`, `index.py`, `retrieve.py` and an “all” runner. It includes configs for SPLADE++ and export to Anserini (quantized). On different hardware:

* **GPU (recommended):** just run; PyTorch picks CUDA. For single GPU there’s a mono-GPU config; otherwise reduce batch sizes vs the 4×V100 settings in the paper configs. ([GitHub][4])
* **CPU:** unset CUDA (e.g., `CUDA_VISIBLE_DEVICES=""`) and lower batch sizes; training will be slow but works because it’s standard PyTorch. The repo notes you must scale regularization/batch sizes when hardware changes. ([GitHub][4])

Quick shape of commands (toy example from repo):

```bash
# fresh env
conda create -n splade_env python=3.9
conda activate splade_env
conda env create -f conda_splade_env.yml

# run everything on a config (GPU or CPU depending on availability)
export PYTHONPATH=$PYTHONPATH:$(pwd)
export SPLADE_CONFIG_NAME="config_default.yaml"
python -m splade.all \
  config.checkpoint_dir=experiments/debug/checkpoint \
  config.index_dir=experiments/debug/index \
  config.out_dir=experiments/debug/out
```

(Adjust to your chosen v3 finetuning config and batch sizes.) ([GitHub][4])

### Option B — Finetune with **Sentence-Transformers SparseEncoder**

Sentence-Transformers ships **SPLADE pooling**, sparse losses, evaluators, and **multi-GPU/ONNX/OpenVINO** support, so you can train on GPU and deploy on **CPU** efficiently. See *SparseEncoder* and SPLADE pooling docs, including “Speeding up Inference” (ONNX/OpenVINO). ([SentenceTransformers][3])
The HF blog also shows how to **train sparse encoders** end-to-end. ([Hugging Face][8])

---

# 2) Building the index (and planning for updates)

You have three solid patterns; all do search on **CPU**.

## A. Lucene/Anserini/Pyserini (impact index)

**Workflow:**

1. **Encode & export SPLADE vectors** to Anserini-readable JSON/TSV using Naver’s helper:

```bash
python -m splade.create_anserini \
  init_dict.model_type_or_dir=naver/splade-v3 \
  config.pretrained_no_yamlconfig=true \
  config.index_dir=/path/to/out_dir \
  +quantization_factor_document=100 \
  +quantization_factor_query=100
```

This writes `docs_anserini.jsonl` and `queries_anserini.tsv` with **quantized impacts** (common practice for learned-sparse; 100× scales to ints). ([GitHub][4])

2. **Index with Anserini** as an **impact** index (Pyserini exposes the searcher):

```python
from pyserini.search import LuceneImpactSearcher
from pyserini.encode.query import SpladeQueryEncoder  # encoder helper

# local Lucene index built from the exported files
searcher = LuceneImpactSearcher('path/to/lucene-index')

# choose device for query encoder: 'cuda:0' or 'cpu'
qenc = SpladeQueryEncoder('naver/splade-v3', device='cpu')
hits = searcher.search(qenc.encode('how do solar panels work?'), k=10)
```

`LuceneImpactSearcher` and `SpladeQueryEncoder` are supported classes in Pyserini (see the module init and encoder factory). ([Hugging Face][5])

**Updates (incremental):**
Lucene supports **add/update/delete** via `IndexWriter.updateDocument()`; in practice, for impact indexes you typically **index deltas** (new/changed docs) and **merge segments** (or periodically rebuild shards) to keep postings consistent and compact. Community threads discuss merging small indexes and caveats of changing field types. For large refreshes, “mini-rebuild then swap” remains common ops strategy. ([Apache Lucene][9])

> Tip: Castorini publish **prebuilt SPLADE-v3 Lucene impact indexes** for BEIR; they’re great for validation and benchmarking before you run your own indexing pipeline. ([Hugging Face][10])

## B. OpenSearch (ML Commons) or Elasticsearch (8.17+)

Both engines now support **neural sparse** natively:

* **OpenSearch**: ML Commons can host sparse models and perform ingest/query inference. OpenSearch 2.12 brought major latency gains for neural sparse over Lucene 9.9, and OpenSearch 3.1 adds a convenient `semantic` field that auto-handles embeddings at ingest/query once you register the model ID. This is ideal for **continuous updates**. ([OpenSearch][6])
* **Elasticsearch**: since **8.17** you can import **HF sparse models** (not just ELSER) via `eland_import_hub_model`, enabling sparse semantic search with standard indices; good for mixed lexical + sparse stacks and real-time updates. ([Elastic][11])

**CPU vs GPU here:** run model inference on either CPU (possibly ONNX Runtime) or GPU nodes; the search itself is Lucene and stays CPU-bound.

## C. PyTerrier + PISA (very fast CPU retrieval)

`pyterrier_splade` shows a tidy pipeline to encode docs/queries and index with **Terrier/PISA**; quantized PISA indexes + MaxScore/BMP yield **sub-millisecond** per-query in some settings with negligible effectiveness loss—handy for high-QPS CPU deployments. ([GitHub][7])

---

# 3) Regular searches (serving)

### A. Lucene/Anserini/Pyserini

* **Query encoding** uses SPLADE on **CPU or GPU** (your choice), then Lucene does the matching/ranking on **CPU**:

```python
from pyserini.search import LuceneImpactSearcher
from pyserini.encode.query import SpladeQueryEncoder

searcher = LuceneImpactSearcher('path/to/lucene-index')
qenc = SpladeQueryEncoder('naver/splade-v3', device='cuda:0')  # or 'cpu'
hits = searcher.search(qenc.encode('best travel card with lounge access'), k=10)
for h in hits:
    print(h.docid, h.score)
```

(CPU is fine if QPS is low; for higher QPS, prefer GPU/ONNX for **query** encoding.) ([Hugging Face][5])

### B. OpenSearch / Elasticsearch

* Register the sparse model; **OpenSearch** `semantic` field simplifies mappings so that ingest/query inference is automatic; **Elasticsearch** 8.17+ can host HF sparse models for similar workflows. Both handle **incremental updates** naturally at ingest time. ([OpenSearch][12])

### C. Sentence-Transformers direct (minimal)

For non-indexed toy scenarios or to embed then hand-roll matching:

```python
from sentence_transformers import SparseEncoder
m = SparseEncoder("naver/splade-v3")   # .to("cpu") or .to("cuda")
q = m.encode_query(["what causes aging fast"])
D = m.encode_document(["doc1 text ...", "doc2 text ..."])
scores = m.similarity(q, D)
```

(Production should use Lucene/Elastic/OpenSearch/PISA for scalable search.) ([Hugging Face][2])

---

# CPU vs GPU by lifecycle stage (summary)

| Stage                            | What benefits from GPU?     | CPU-only viable? | Notes                                                                                                                          |
| -------------------------------- | --------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Training/Finetune**            | Yes (transformers training) | Yes (slow)       | Use Naver `splade` or Sentence-Transformers training; lower batch size; adjust FLOPS regularization accordingly. ([GitHub][4]) |
| **Document encoding (indexing)** | Helpful at scale            | Yes              | Batch encode docs; for CPU consider **ONNX/OpenVINO** exports to speed up. ([SentenceTransformers][3])                         |
| **Query encoding**               | Helpful at higher QPS       | Yes              | Encode queries with SparseEncoder on CPU or GPU; **search itself is CPU (Lucene)**. ([SentenceTransformers][3])                |
| **Searching**                    | Not needed                  | Yes              | Lucene/Elastic/OpenSearch inverted index—pure CPU. ([PyPI][13])                                                                |

---

# Incremental updates: what to expect

* **Lucene/Anserini**: You can **append/merge** new segments or **update** specific docs (delete+add). Operationally, teams often maintain **delta indexes** then merge or periodically rebuild per shard for cleanliness and consistency of impact weights. (See Lucene API and Pyserini issues discussing incremental additions/merges.) ([Apache Lucene][9])
* **OpenSearch / Elasticsearch**: built for **streaming ingestion**. Register the sparse model and let the engine compute vectors at **ingest-time** (or on the client) and update the inverted index in near real-time. ([OpenSearch][12])

---

# A sensible “starter” architecture

1. **Prototype & validate** with prebuilt SPLADE-v3 BEIR indexes (sanity-check quality). ([Hugging Face][10])
2. **Index your data with Anserini (impact)** using Naver’s `create_anserini` export (quantization=100). ([GitHub][4])
3. **Serve with Pyserini** + `LuceneImpactSearcher`, and choose **CPU or GPU** for the **query encoder**. ([Hugging Face][5])
4. If you prefer a managed cluster and easy updates, consider **OpenSearch’s `semantic` field** or **Elasticsearch 8.17+** sparse-model import instead. ([OpenSearch][12])

---

# Minimal code you can adapt

### Index creation (export SPLADE vectors → Anserini JSON/TSV)

```bash
python -m splade.create_anserini \
  init_dict.model_type_or_dir=naver/splade-v3 \
  config.pretrained_no_yamlconfig=true \
  config.index_dir=/data/my_corpus_splade \
  +quantization_factor_document=100 +quantization_factor_query=100
# Then run Anserini's IndexCollection (impact) on docs_anserini.jsonl
```

([GitHub][4])

### Searching (CPU or GPU query encoder)

```python
from pyserini.search import LuceneImpactSearcher
from pyserini.encode.query import SpladeQueryEncoder

searcher = LuceneImpactSearcher('/data/lucene-impact-index')
# toggle here:
qenc = SpladeQueryEncoder('naver/splade-v3', device='cpu')   # or 'cuda:0'

def search(q):
    return searcher.search(qenc.encode(q), k=10)

for h in search("renewable energy incentives"):
    print(h.docid, h.score)
```

([Hugging Face][5])

---

# Performance & ops tips

* **CPU acceleration:** export the SparseEncoder to **ONNX** or **OpenVINO** (Sentence-Transformers docs) for faster CPU query/doc encoding. ([SentenceTransformers][3])
* **Memory control on CPU:** the SPLADE pooling module exposes a `chunk_size` arg to reduce peak memory. ([SentenceTransformers][3])
* **Fast retrieval backends:** PISA + block-max pruning/MaxScore can deliver **sub-ms** latency on CPU for SPLADE-style indexes. ([Antonio Mallia][14])
* **Hybrid search:** you can mix Lucene BM25 + SPLADE or even dense (Lucene HNSW) within the same stack for better recall. ([arXiv][15])
* **Licensing:** `naver/splade-v3` is **CC BY-NC-SA 4.0** (non-commercial). Verify your use case. ([Hugging Face][2])
* **Heads-up:** Pyserini’s issue tracker occasionally notes SPLADE-v3 index quirks; pin a recent version and watch the tracker. ([GitHub][16])

---

## One-line TL;DR

* **Train/finetune** on **GPU** (CPU works but slow) using Naver’s repo or Sentence-Transformers.
* **Index & search** on **CPU** with Lucene/Anserini (impact) or managed engines (OpenSearch/Elasticsearch); **only the encoder** benefits from GPU at query time.
* For **updates**, append/merge segments (Lucene) or let OpenSearch/Elasticsearch handle ingest-time inference and indexing.

If you want, tell me your data size, SLA, and stack (standalone vs managed cluster), and I’ll tailor concrete configs (batch sizes, indexer flags, and hardware sizing).

[1]: https://arxiv.org/abs/2403.06789?utm_source=chatgpt.com "SPLADE-v3: New baselines for SPLADE"
[2]: https://huggingface.co/naver/splade-v3 "naver/splade-v3 · Hugging Face"
[3]: https://sbert.net/docs/package_reference/sparse_encoder/models.html "Modules — Sentence Transformers  documentation"
[4]: https://github.com/naver/splade "GitHub - naver/splade: SPLADE: sparse neural search (SIGIR21, SIGIR22)"
[5]: https://huggingface.co/spaces/castorini/ONNX-Demo/blob/f77c5c674639ab1684cf5d8e248d344ff1d95e25/pyserini/search/__init__.py?utm_source=chatgpt.com "pyserini/search/__init__.py · castorini/ONNX-Demo ..."
[6]: https://opensearch.org/blog/a-deep-dive-into-faster-semantic-sparse-retrieval-in-os-2-12/?utm_source=chatgpt.com "A deep dive into faster semantic sparse retrieval in ..."
[7]: https://github.com/cmacdonald/pyt_splade "GitHub - cmacdonald/pyt_splade"
[8]: https://huggingface.co/blog/train-sparse-encoder?utm_source=chatgpt.com "Training and Finetuning Sparse Embedding Models with ..."
[9]: https://lucene.apache.org/core/8_0_0/core/org/apache/lucene/index/package-summary.html?utm_source=chatgpt.com "org.apache.lucene.index (Lucene 8.0.0 API)"
[10]: https://huggingface.co/datasets/castorini/prebuilt-indexes-beir/blob/main/lucene-inverted/splade-v3/lucene-inverted.beir-v1.0.0-splade-v3.20250603.168a2d.README.md?utm_source=chatgpt.com "BEIR (v1.0.0): SPLADE-v3 Indexes - lucene-inverted"
[11]: https://www.elastic.co/search-labs/blog/sparse-vector-embedding?utm_source=chatgpt.com "Understanding sparse vector embeddings with trained ML ..."
[12]: https://opensearch.org/blog/the-new-semantic-field-simplifying-semantic-search-in-opensearch/?utm_source=chatgpt.com "The new semantic field: Simplifying semantic search in ..."
[13]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"
[14]: https://www.antoniomallia.it/uploads/SIGIR24.pdf?utm_source=chatgpt.com "Faster Learned Sparse Retrieval with Block-Max Pruning"
[15]: https://arxiv.org/pdf/2304.12139?utm_source=chatgpt.com "Anserini Gets Dense Retrieval: Integration of Lucene's ..."
[16]: https://github.com/castorini/pyserini/issues?utm_source=chatgpt.com "Issues · castorini/pyserini"
