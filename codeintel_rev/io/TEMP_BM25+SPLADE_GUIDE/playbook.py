# ruff: noqa: ALL
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

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

try:
    import ujson as _json
except Exception:
    _json = json

# ---------------------------
# Helpers
# ---------------------------


def info(x):
    print(f"[INFO] {x}", flush=True)


def warn(x):
    print(f"[WARN] {x}", flush=True)


def err(x):
    print(f"[ERROR] {x}", file=sys.stderr, flush=True)


def require_path(p: Path, kind="file"):
    if kind == "file" and not p.is_file():
        err(f"Missing file: {p}")
        sys.exit(1)
    if kind == "dir" and not p.is_dir():
        err(f"Missing dir:  {p}")
        sys.exit(1)


def stream_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield _json.loads(line)


def pseudo_bow(decoded: list[tuple[str, float]], q=100, max_terms=3000) -> str:
    """Repeat tokens proportional to integer impacts (SPLADE impact query convention)."""
    toks = []
    for tok, w in decoded:
        if w <= 0:
            continue
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
            scores[docid] = scores.get(docid, 0.0) + 1.0 / (k + r)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:topk]


# ---------------------------
# Subcommands
# ---------------------------


def cmd_export(a):
    """Export SPLADE-v3 to ONNX (+ optional int8 dynamic quant)."""
    from sentence_transformers import SparseEncoder

    info(f"Exporting '{a.model_id}' → ONNX at {a.out_dir}")
    out_dir = Path(a.out_dir)
    (out_dir / "onnx").mkdir(parents=True, exist_ok=True)

    # Base ONNX export via backend
    enc = SparseEncoder(a.model_id, backend="onnx")
    enc.save_pretrained(str(out_dir))
    base = out_dir / "onnx" / "model.onnx"
    if base.exists():
        info(f"Base ONNX: {base}")
    else:
        warn(
            "ONNX export expected but not found; upgrade sentence-transformers if needed."
        )

    # Optimize (O3) & quantize (int8)
    if a.optimize:
        from sentence_transformers import export_optimized_onnx_model

        export_optimized_onnx_model(
            enc,
            optimization_config="O3",
            model_name_or_path=str(out_dir),
            push_to_hub=False,
            create_pr=False,
        )
        info("Saved optimized ONNX (O3).")
    if a.quantize:
        try:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            qpath = out_dir / "onnx" / "model_qint8.onnx"
            quantize_dynamic(
                str(base), str(qpath), weight_type=QuantType.QInt8, optimize_model=True
            )
            info(f"Saved int8 dynamic-quantized ONNX: {qpath}")
        except Exception as e:
            warn(f"Quantization skipped (onnxruntime.quantization missing?): {e}")


def cmd_prepare_bm25(a):
    """Normalize corpus.jsonl -> JsonCollection for BM25."""
    src = Path(a.corpus)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    require_path(src, "file")
    n = 0
    for obj in stream_jsonl(src):
        docid = str(obj["id"])
        contents = obj.get("contents") or obj.get("text") or ""
        with (out / f"{docid}.json").open("w", encoding="utf-8") as w:
            _json.dump({"id": docid, "contents": contents}, w)
        n += 1
        if n % 10000 == 0:
            info(f"wrote {n} docs …")
    info(f"✅ BM25 JsonCollection at {out} ({n} docs)")


def _run_pyserini_index(cmd: list[str]):
    info("Launching: " + " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        err("Indexing failed")
        sys.exit(r.returncode)


def cmd_index_bm25(a):
    """Build BM25 index."""
    cmd = [
        sys.executable,
        "-m",
        "pyserini.index.lucene",
        "--collection",
        "JsonCollection",
        "--input",
        a.json_dir,
        "--index",
        a.index_dir,
        "--generator",
        "DefaultLuceneDocumentGenerator",
        "--threads",
        str(a.threads),
        "--storePositions",
        "--storeDocvectors",
        "--storeRaw",
    ]
    _run_pyserini_index(cmd)
    info(f"✅ BM25 index at {a.index_dir}")


def cmd_encode(a):
    """Encode corpus.jsonl -> JsonVectorCollection using SPLADE (ONNX)."""
    from sentence_transformers import SparseEncoder
    from tqdm import tqdm

    src = Path(a.corpus)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    require_path(src, "file")
    model_kwargs = {"provider": a.provider}
    if a.onnx_file:
        model_kwargs["file_name"] = a.onnx_file
    enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=model_kwargs)

    def to_vec(decoded):
        v = {}
        for tok, w in decoded:
            if w > 0:
                iw = int(round(w * a.quant))
                if iw > 0:
                    v[tok] = iw
        return v

    batch_ids, batch_texts = [], []
    shard_i, n = 0, 0
    writer = None

    def open_writer(i):
        return (out / f"part-{i:05d}.jsonl").open("w", encoding="utf-8")

    def flush():
        nonlocal writer, shard_i, n
        if not batch_texts:
            return
        emb = enc.encode_document(batch_texts)
        decs = enc.decode(emb, top_k=None)
        for docid, dec in zip(batch_ids, decs):
            rec = {"id": docid, "contents": "", "vector": to_vec(dec)}
            if writer is None:
                writer = open_writer(shard_i)
            writer.write(_json.dumps(rec) + "\n")
            n += 1
            if n % a.shard_size == 0:
                writer.close()
                writer = None
                shard_i += 1
        batch_ids.clear()
        batch_texts.clear()

    info(
        f"Encoding with ONNX: model_dir={a.model_dir}, file={a.onnx_file}, provider={a.provider}"
    )
    for obj in tqdm(stream_jsonl(src), desc="encode-docs"):
        docid = str(obj["id"])
        text = obj.get("contents") or obj.get("text") or ""
        batch_ids.append(docid)
        batch_texts.append(text)
        if len(batch_texts) >= a.batch:
            flush()
    flush()
    if writer:
        writer.close()
    info(f"✅ Wrote {n} vectors to {a.out_dir}")


def cmd_index_splade(a):
    """Build Lucene impact index from JsonVectorCollection."""
    # Helpful when SPLADE expands queries a lot:
    os.environ.setdefault(
        "JAVA_TOOL_OPTIONS", f"-Dorg.apache.lucene.maxClauseCount={a.max_clause}"
    )
    cmd = [
        sys.executable,
        "-m",
        "pyserini.index.lucene",
        "--collection",
        "JsonVectorCollection",
        "--input",
        a.vectors_dir,
        "--index",
        a.index_dir,
        "--generator",
        "DefaultLuceneDocumentGenerator",
        "--threads",
        str(a.threads),
        "--impact",
        "--pretokenized",
        "--optimize",
    ]
    _run_pyserini_index(cmd)
    info(f"✅ SPLADE impact index at {a.index_dir}")


def cmd_search(a):
    """Single-query search: bm25 | splade | hybrid."""
    from pyserini.search.lucene import LuceneImpactSearcher, LuceneSearcher

    if a.mode in ("splade", "hybrid"):
        from sentence_transformers import SparseEncoder

        mk = {"provider": a.provider}
        if a.onnx_file:
            mk["file_name"] = a.onnx_file
        enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)

    def run_bm25(q):
        s = LuceneSearcher(a.bm25_index)
        if a.k1 is not None and a.b is not None:
            s.set_bm25(a.k1, a.b)  # documented BM25 API
        return [(h.docid, h.score) for h in s.search(q, k=a.k)]

    def run_splade(q):
        qemb = enc.encode_query([q])
        dec = enc.decode(qemb, top_k=None)[0]
        qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
        s = LuceneImpactSearcher(a.splade_index)
        return [(h.docid, h.score) for h in s.search(qstr, k=a.k)]

    if a.mode == "bm25":
        hits = run_bm25(a.query)
    elif a.mode == "splade":
        hits = run_splade(a.query)
    else:
        bm = run_bm25(a.query)
        sp = run_splade(a.query)
        hits = rrf_fuse(bm, sp, k=a.rrf_k, topk=a.k)

    for i, (doc, score) in enumerate(hits, 1):
        print(i, doc, f"{score:.4f}")


def _read_topics(tsv_path: Path):
    q = {}
    with tsv_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            qid, query = line.rstrip("\n").split("\t", 1)
            q[qid] = query
    return q


def cmd_search_batch(a):
    """Batch search; writes a TREC run file."""
    from pyserini.search.lucene import LuceneImpactSearcher, LuceneSearcher

    topics = _read_topics(Path(a.topics))
    run = {}

    # Prepare searchers
    bm25 = None
    splade = None
    enc = None
    if a.mode in ("bm25", "hybrid"):
        bm25 = LuceneSearcher(a.bm25_index)
        if a.k1 is not None and a.b is not None:
            bm25.set_bm25(a.k1, a.b)  # BM25 params
    if a.mode in ("splade", "hybrid"):
        from sentence_transformers import SparseEncoder

        mk = {"provider": a.provider}
        if a.onnx_file:
            mk["file_name"] = a.onnx_file
        enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)
        splade = LuceneImpactSearcher(a.splade_index)

    for qid, qtext in topics.items():
        if a.mode == "bm25":
            hits = bm25.search(qtext, k=a.k)
            run[qid] = [(h.docid, h.score) for h in hits]
        elif a.mode == "splade":
            qemb = enc.encode_query([qtext])
            dec = enc.decode(qemb, top_k=None)[0]
            qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
            hits = splade.search(qstr, k=a.k)
            run[qid] = [(h.docid, h.score) for h in hits]
        else:
            bm = bm25.search(qtext, k=a.k_fusion)
            qemb = enc.encode_query([qtext])
            dec = enc.decode(qemb, top_k=None)[0]
            qstr = pseudo_bow(dec, q=a.quant, max_terms=a.max_terms)
            sp = splade.search(qstr, k=a.k_fusion)
            run[qid] = rrf_fuse(
                [(h.docid, h.score) for h in bm],
                [(h.docid, h.score) for h in sp],
                k=a.rrf_k,
                topk=a.k,
            )

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_trec_run(run, out, tag=a.tag)
    info(f"✅ wrote run file: {out}")


def cmd_eval(a):
    """Call pyserini.eval.trec_eval to compute metrics like MAP/NDCG@10."""
    require_path(Path(a.qrels), "file")
    require_path(Path(a.run), "file")
    # Example: python -m pyserini.eval.trec_eval -c -m ndcg_cut.10 -m map qrels.txt run.trec
    cmd = [sys.executable, "-m", "pyserini.eval.trec_eval", "-c"]
    for m in a.metric:
        cmd += ["-m", m]
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

            s = LuceneSearcher(a.bm25_index)
            s.set_bm25(k1, b)
            run = {}
            for qid, q in topics.items():
                hits = s.search(q, k=a.k)
                run[qid] = [(h.docid, h.score) for h in hits]
            run_path = tmpdir / f"run.k1_{k1:.3f}.b_{b:.3f}.trec"
            write_trec_run(run, run_path, tag=f"bm25_k1{k1}_b{b}")
            # Evaluate ndcg_cut.10 (or any metric list)
            cmd = [
                sys.executable,
                "-m",
                "pyserini.eval.trec_eval",
                "-c",
                "-m",
                a.metric,
                a.qrels,
                str(run_path),
            ]
            out = subprocess.run(
                cmd, check=False, capture_output=True, text=True
            ).stdout
            score = None
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == a.metric and parts[1] == "all":
                    score = float(parts[2])
                    break
            if score is None:
                warn(f"Could not parse metric for k1={k1},b={b}")
            else:
                info(f"k1={k1:.2f}, b={b:.2f} → {a.metric}={score:.5f}")
                if score > best[2]:
                    best = (k1, b, score)
    print(f"BEST: k1={best[0]:.3f}, b={best[1]:.3f}, {a.metric}={best[2]:.5f}")


def cmd_train(a):
    """Minimal SPLADE finetuning on triples JSONL (uses GPU if available)."""
    import torch
    import ujson
    from datasets import IterableDataset
    from sentence_transformers import SparseEncoder
    from sentence_transformers.sparse_encoder.losses import (
        FlopsLoss,
        SparseMultipleNegativesRankingLoss,
        SpladeLoss,
    )
    from sentence_transformers.sparse_encoder.training import (
        SparseEncoderTrainer,
        SparseEncoderTrainingArguments,
    )

    class Triples(IterableDataset):
        def __iter__(self):
            with Path(a.train_file).open("r", encoding="utf-8") as f:
                for line in f:
                    ex = ujson.loads(line)
                    yield {
                        "query": ex["query"],
                        "pos": ex["positive"],
                        "neg": ex.get("negative", ""),
                    }

    device = "cuda" if torch.cuda.is_available() else "cpu"
    info(f"Loading base model {a.base_model} on {device}")
    model = SparseEncoder(a.base_model, device=device)

    mnrl = SparseMultipleNegativesRankingLoss(model=model)
    sreg = SpladeLoss(model=model)
    flops = FlopsLoss(model=model)

    args = SparseEncoderTrainingArguments(
        output_dir=a.out_dir,
        per_device_train_batch_size=a.batch,
        num_train_epochs=a.epochs,
        learning_rate=a.lr,
        logging_steps=100,
        save_steps=a.save_steps,
        remove_unused_columns=False,
    )
    trainer = SparseEncoderTrainer(
        model=model, args=args, train_dataset=Triples(), loss=[mnrl, sreg, flops]
    )
    trainer.train()
    model.save_pretrained(a.out_dir)
    info(f"✅ Saved finetuned model to {a.out_dir}")
    info(
        "Tip: re-run `export` with --model-id set to this directory to create optimized ONNX."
    )


def cmd_bench(a):
    """Micro-benchmark ONNX query encoding latency."""
    from sentence_transformers import SparseEncoder

    texts = [a.query] * a.batch
    mk = {"provider": a.provider}
    if a.onnx_file:
        mk["file_name"] = a.onnx_file
    enc = SparseEncoder(a.model_dir, backend="onnx", model_kwargs=mk)
    for _ in range(10):
        enc.encode_query(texts)  # warmup
    l = []
    for _ in range(a.repeats):
        t0 = time.time()
        enc.encode_query(texts)
        l.append(1000 * (time.time() - t0))
    l.sort()
    p50 = l[len(l) // 2]
    p95 = l[int(0.95 * (len(l) - 1))]
    print(f"p50={p50:.1f}ms  p95={p95:.1f}ms  (batch={a.batch}, repeats={a.repeats})")


# ---------------------------
# CLI
# ---------------------------


def build_cli():
    p = argparse.ArgumentParser(
        prog="playbook.py",
        description="SPLADE-v3 (ONNX) + BM25 with Pyserini — unified playbook",
    )
    s = p.add_subparsers(dest="cmd", required=True)

    sp = s.add_parser(
        "export", help="Export SPLADE-v3 to ONNX, optionally optimize/quantize."
    )
    sp.add_argument("--model-id", default="naver/splade-v3")
    sp.add_argument("--out-dir", default="models/splade-v3")
    sp.add_argument("--optimize", action="store_true")
    sp.add_argument("--quantize", action="store_true")
    sp.set_defaults(func=cmd_export)

    sp = s.add_parser("prepare-bm25", help="Normalize corpus.jsonl -> JsonCollection.")
    sp.add_argument("--corpus", default="data/corpus.jsonl")
    sp.add_argument("--out-dir", default="data/jsonl")
    sp.set_defaults(func=cmd_prepare_bm25)

    sp = s.add_parser("index-bm25", help="Build BM25 index.")
    sp.add_argument("--json-dir", default="data/jsonl")
    sp.add_argument("--index-dir", default="indexes/bm25")
    sp.add_argument("--threads", type=int, default=8)
    sp.set_defaults(func=cmd_index_bm25)

    sp = s.add_parser(
        "encode", help="Encode corpus -> SPLADE JsonVectorCollection with ONNX."
    )
    sp.add_argument("--corpus", default="data/corpus.jsonl")
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--out-dir", default="data/splade_vectors")
    sp.add_argument("--batch", type=int, default=32)
    sp.add_argument("--quant", type=int, default=100)
    sp.add_argument("--shard-size", type=int, default=100_000)
    sp.set_defaults(func=cmd_encode)

    sp = s.add_parser("index-splade", help="Build SPLADE impact index.")
    sp.add_argument("--vectors-dir", default="data/splade_vectors")
    sp.add_argument("--index-dir", default="indexes/splade_v3_impact")
    sp.add_argument("--threads", type=int, default=16)
    sp.add_argument("--max-clause", type=int, default=4096)
    sp.set_defaults(func=cmd_index_splade)

    sp = s.add_parser("search", help="Single query: bm25 | splade | hybrid (RRF).")
    sp.add_argument("--mode", choices=["bm25", "splade", "hybrid"], required=True)
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

    sp = s.add_parser(
        "search-batch", help="Batch search from topics TSV -> TREC run file."
    )
    sp.add_argument("--mode", choices=["bm25", "splade", "hybrid"], required=True)
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

    sp = s.add_parser("eval", help="Evaluate a run with pyserini.eval.trec_eval.")
    sp.add_argument("--qrels", required=True)
    sp.add_argument("--run", required=True)
    sp.add_argument("--metric", action="append", default=["ndcg_cut.10", "map"])
    sp.set_defaults(func=cmd_eval)

    sp = s.add_parser("tune-bm25", help="Grid-search BM25 (k1,b) on topics+qrels.")
    sp.add_argument("--bm25-index", default="indexes/bm25")
    sp.add_argument("--topics", required=True)
    sp.add_argument("--qrels", required=True)
    sp.add_argument("--k", type=int, default=1000)
    sp.add_argument("--metric", default="ndcg_cut.10")
    sp.add_argument("--k1-grid", type=float, nargs="+", default=[0.6, 0.9, 1.2, 1.5])
    sp.add_argument("--b-grid", type=float, nargs="+", default=[0.2, 0.4, 0.6, 0.8])
    sp.set_defaults(func=cmd_tune_bm25)

    sp = s.add_parser("train", help="(Optional) Finetune SPLADE on triples JSONL.")
    sp.add_argument(
        "--train-file", required=True, help='Lines: {"query","positive","negative"}'
    )
    sp.add_argument("--base-model", default="naver/splade-v3")
    sp.add_argument("--out-dir", default="models/splade-finetuned")
    sp.add_argument("--epochs", type=int, default=1)
    sp.add_argument("--batch", type=int, default=16)
    sp.add_argument("--lr", type=float, default=2e-5)
    sp.add_argument("--save-steps", type=int, default=1000)
    sp.set_defaults(func=cmd_train)

    sp = s.add_parser("bench", help="Micro-benchmark ONNX query encoding.")
    sp.add_argument("--model-dir", default="models/splade-v3")
    sp.add_argument("--onnx-file", default="onnx/model_qint8.onnx")
    sp.add_argument("--provider", default="CPUExecutionProvider")
    sp.add_argument("--query", default="how to claim solar credits")
    sp.add_argument("--batch", type=int, default=8)
    sp.add_argument("--repeats", type=int, default=50)
    sp.set_defaults(func=cmd_bench)

    return p


def main():
    cli = build_cli()
    args = cli.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
