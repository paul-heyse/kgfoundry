#!/usr/bin/env python3
"""High-recall harness for BM25 + RM3 and (optionally) SPLADE.

This script evaluates Recall@K over a query set while sweeping BM25 (k1, b)
and RM3 configurations. It also supports an *auto* mode that applies the same
RM3 heuristics used in production to validate toggle decisions.

Usage
-----
python tools/recall_harness.py +  --bm25-index ~/indexes/bm25 +  --queries data/queries.jsonl +  --qrels data/qrels.tsv +  --k 10 +  --sweep-k1 0.6,0.9,1.2 +  --sweep-b 0.2,0.4,0.75 +  --rm3 off,10-10-0.5,20-10-0.5 +  --auto-rm3 true +  --outdir runs/2025-11-11

Input formats
-------------
* queries.jsonl: one JSON per line: {"qid": "...", "text": "..."}
* qrels.tsv: TREC qrels TSV: qid <tab> docid <tab> rel (rel>0 = relevant)

Outputs
-------
* summary.json        : per-configuration Recall@K, MRR@K (optional), decisions
* decisions.csv       : per-query RM3 decisions in auto mode (enable/disable)
* runs/*.tsv          : simple runs for debugging

Notes
-----
* Requires Pyserini for BM25/RM3. SPLADE evaluation is optional (provide
  --splade-index and --splade-encoder to enable; used for hybrid oracle).
* Designed to be run in CI/nightly as a regression guard.

"""

from __future__ import annotations

import argparse
import csv
import dataclasses as dc
import json
from collections.abc import Iterable, Mapping
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _read_qrels(path: Path) -> dict[str, set[int]]:
    gold: dict[str, set[int]] = {}
    with path.open() as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row:
                continue
            qid, docid, rel = row[0], row[1], int(row[2])
            if rel > 0:
                gold.setdefault(qid, set()).add(int(docid))
    return gold


@dc.dataclass(frozen=True)
class RM3Params:
    """Parameters for RM3 (Relevance Model 3) query expansion.

    RM3 is a pseudo-relevance feedback technique that expands queries using
    terms from top-ranked documents. This dataclass encapsulates the three
    key parameters that control RM3 behavior.

    Attributes
    ----------
    fb_docs : int
        Number of top-ranked documents to use for feedback. Higher values
        include more documents but may introduce noise. Typical values range
        from 5 to 20.
    fb_terms : int
        Number of expansion terms to add to the original query. Higher values
        add more terms but may dilute query intent. Typical values range from
        10 to 50.
    orig_weight : float
        Weight given to the original query terms (0.0 to 1.0). Higher values
        preserve more of the original query intent. Typical values range from
        0.3 to 0.7. The expansion terms receive weight (1.0 - orig_weight).

    Notes
    -----
    RM3 is used to improve recall by expanding queries with relevant terms
    from top-ranked documents. The parameters control the trade-off between
    recall improvement and query drift. Common configurations include
    "10-10-0.5" (10 docs, 10 terms, 0.5 weight) and "20-10-0.5" (20 docs,
    10 terms, 0.5 weight).
    """

    fb_docs: int
    fb_terms: int
    orig_weight: float


class RM3Heuristics:
    """Copy of the production heuristic (kept self-contained here)."""

    def __init__(
        self, *, short_query_max_terms: int = 3, symbol_like_regex: str | None = None
    ) -> None:
        import re

        self._tok_re = re.compile(r"[^A-Za-z0-9_]+")
        self._sym_re = re.compile(
            symbol_like_regex
            or r"(?:\w+::\w+)|(?:\w+\.\w+)|(?:[/\\])|(?:[A-Za-z]+[A-Z][a-z]+)|(?:[A-Za-z_]+\d+)"
        )
        self._short = short_query_max_terms

    def should_enable(self, q: str) -> bool:
        """Determine whether RM3 should be enabled for a given query.

        This method implements production heuristics for deciding when RM3
        query expansion is beneficial. RM3 is enabled for short queries
        (which benefit from expansion) but disabled for queries containing
        symbol-like patterns (which are typically precise and don't benefit
        from expansion).

        Parameters
        ----------
        q : str
            The query string to evaluate. The query is tokenized and analyzed
            for length and symbol-like patterns.

        Returns
        -------
        bool
            True if RM3 should be enabled for this query, False otherwise.
            Returns True for short queries (≤ short_query_max_terms tokens)
            and queries without symbol-like patterns. Returns False for queries
            containing symbol-like patterns (e.g., "Class::method", "file.path",
            "CamelCase", "snake_case123").

        Notes
        -----
        The heuristic is based on the observation that short queries benefit
        from expansion (more recall), while symbol-like queries are typically
        precise identifiers that don't benefit from expansion and may suffer
        from query drift. This matches the production heuristic used in the
        CodeIntel MCP server.
        """
        toks = [t for t in self._tok_re.split(q.lower()) if t]
        if len(toks) <= self._short:
            return True
        if self._sym_re.search(q):
            return False
        return True


def _lucene_searcher(index_dir: Path, k1: float, b: float):
    from importlib import import_module

    lucene = import_module("pyserini.search.lucene")
    s = lucene.LuceneSearcher(str(index_dir))
    try:
        s.set_bm25(k1, b)
    except TypeError:
        s.set_bm25(k1=k1, b=b)
    return s


def _apply_rm3(searcher, p: RM3Params | None) -> None:
    if p is None:
        return
    try:
        searcher.set_rm3(p.fb_docs, p.fb_terms, p.orig_weight)
    except TypeError:
        searcher.set_rm3(
            fb_docs=p.fb_docs, fb_terms=p.fb_terms, original_query_weight=p.orig_weight
        )


def _recall_at_k(run: Mapping[str, list[int]], qrels: Mapping[str, set[int]], k: int) -> float:
    num = 0
    den = 0
    for qid, gold in qrels.items():
        den += 1
        preds = run.get(qid, [])[:k]
        if any(d in gold for d in preds):
            num += 1
    return (num / den) if den else 0.0


def _mrr_at_k(run: Mapping[str, list[int]], qrels: Mapping[str, set[int]], k: int) -> float:
    import math

    total = 0.0
    den = 0
    for qid, gold in qrels.items():
        den += 1
        rank = math.inf
        for i, d in enumerate(run.get(qid, [])[:k], start=1):
            if d in gold:
                rank = i
                break
        total += 0 if math.isinf(rank) else 1.0 / rank
    return (total / den) if den else 0.0


def _parse_rm3_list(spec: str) -> list[RM3Params | None]:
    out: list[RM3Params | None] = []
    for tok in spec.split(","):
        tok = tok.strip().lower()
        if not tok or tok == "off" or tok == "none":
            out.append(None)
        else:
            a, b, w = tok.split("-")
            out.append(RM3Params(int(a), int(b), float(w)))
    return out


def _write_run(path: Path, run: Mapping[str, list[int]]) -> None:
    with path.open("w") as f:
        for q, docs in run.items():
            for rank, d in enumerate(docs, start=1):
                f.write(f"{q}\t{d}\t{rank}\n")


def sweep(
    *,
    index_dir: Path,
    queries: list[dict],
    qrels: dict[str, set[int]],
    k: int,
    k1s: Iterable[float],
    bs: Iterable[float],
    rm3s: Iterable[RM3Params | None],
    auto_rm3: bool,
    outdir: Path,
) -> dict:
    """Sweep BM25 and RM3 configurations and evaluate Recall@K.

    This function performs a grid search over BM25 parameters (k1, b) and RM3
    configurations, evaluating Recall@K and MRR@K for each combination. It supports
    both fixed RM3 configurations and automatic per-query RM3 decisions based
    on heuristics. Results are written to the output directory as JSON summaries
    and TSV run files.

    Parameters
    ----------
    index_dir : Path
        Path to the BM25 index directory. The index must be compatible with
        Pyserini's LuceneSearcher format.
    queries : list[dict]
        List of query dictionaries, each containing "qid" and "text" keys.
        Queries are evaluated against the index to compute recall metrics.
    qrels : dict[str, set[int]]
        Ground truth relevance judgments. Keys are query IDs (qid), values are
        sets of relevant document IDs. Used to compute Recall@K and MRR@K.
    k : int
        The cutoff rank for Recall@K and MRR@K evaluation. Only the top K
        results are considered when computing recall metrics.
    k1s : Iterable[float]
        Iterable of BM25 k1 parameter values to sweep. k1 controls term
        frequency saturation. Typical values range from 0.6 to 1.5.
    bs : Iterable[float]
        Iterable of BM25 b parameter values to sweep. b controls length
        normalization. Typical values range from 0.2 to 0.75.
    rm3s : Iterable[RM3Params | None]
        Iterable of RM3 parameter configurations to sweep. None values
        indicate RM3 is disabled. Each RM3Params instance specifies
        fb_docs, fb_terms, and orig_weight.
    auto_rm3 : bool
        If True, enables automatic per-query RM3 decisions using heuristics.
        When enabled, RM3 is applied selectively based on query characteristics
        (short queries get RM3, symbol-like queries don't). When False, uses
        the fixed RM3 configurations from rm3s.
    outdir : Path
        Output directory for results. The directory is created if it doesn't
        exist. Results include summary.json (best and all configurations),
        decisions.csv (per-query RM3 decisions when auto_rm3=True), and
        run files (TSV format) for each configuration.

    Returns
    -------
    dict
        Summary dictionary containing "best" (best configuration by Recall@K)
        and "all" (all configurations sorted by Recall@K descending). Each
        configuration entry includes "tag" (configuration metadata), "recall_at_k"
        (Recall@K score), and "mrr_at_k" (MRR@K score).

    Notes
    -----
    This function performs a full grid search over all combinations of k1, b,
    and RM3 configurations. For each combination, it runs all queries and
    computes recall metrics. When auto_rm3 is enabled, RM3 decisions are
    made per-query using RM3Heuristics.should_enable(). Results are written
    to disk for analysis and debugging. The function is designed for batch
    evaluation and regression testing in CI/nightly jobs.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    # optional auto RM3
    auto = RM3Heuristics() if auto_rm3 else None

    results: list[dict] = []
    decisions_path = outdir / "decisions.csv"
    with decisions_path.open("w", newline="") as dcsv:
        dwr = csv.writer(dcsv)
        dwr.writerow(["qid", "query", "auto_rm3_enabled"])  # filled only when auto_rm3

        for k1 in k1s:
            for b in bs:
                for rm3 in rm3s:
                    # Build two searchers: base and RM3-enabled (for auto mode we switch per-q)
                    searcher_base = _lucene_searcher(index_dir, k1, b)
                    searcher_rm3 = _lucene_searcher(index_dir, k1, b)
                    _apply_rm3(searcher_rm3, rm3)

                    run: dict[str, list[int]] = {}
                    for q in queries:
                        qid = str(q["qid"])
                        text = str(q["text"]).strip()
                        if not text:
                            run[qid] = []
                            continue
                        if auto is not None:
                            enable = auto.should_enable(text)
                            dwr.writerow([qid, text, int(enable)])
                            s = searcher_rm3 if enable else searcher_base
                        else:
                            s = searcher_rm3 if rm3 is not None else searcher_base
                        hits = s.search(text, k=k)
                        run[qid] = [int(h.docid) for h in hits]

                    r_at_k = _recall_at_k(run, qrels, k)
                    mrr_at_k = _mrr_at_k(run, qrels, k)

                    tag = {
                        "engine": "bm25",
                        "k1": k1,
                        "b": b,
                        "rm3": None if rm3 is None else dc.asdict(rm3),
                        "auto_rm3": bool(auto is not None),
                        "k": k,
                    }
                    results.append(
                        {
                            "tag": tag,
                            "recall_at_k": r_at_k,
                            "mrr_at_k": mrr_at_k,
                        }
                    )
                    _write_run(
                        outdir
                        / f"run.k1={k1}.b={b}.rm3={'auto' if auto else ('off' if rm3 is None else 'on')}.tsv",
                        run,
                    )

    results.sort(key=lambda r: (r["recall_at_k"], r["mrr_at_k"]), reverse=True)
    summary = {"best": results[0] if results else None, "all": results}
    with (outdir / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary


def main() -> None:
    """Main entry point for the recall harness script.

    This function parses command-line arguments, loads queries and relevance
    judgments, parses parameter sweep specifications, and invokes the sweep
    function to evaluate BM25 and RM3 configurations. The best configuration
    (by Recall@K) is printed to stdout as JSON.

    Parameters
    ----------
    None
        All parameters are provided via command-line arguments:
        --bm25-index: Path to BM25 index directory (required)
        --queries: Path to queries JSONL file (required)
        --qrels: Path to relevance judgments TSV file (required)
        --k: Recall@K cutoff (default: 10)
        --sweep-k1: Comma-separated k1 values (default: "0.9,1.2")
        --sweep-b: Comma-separated b values (default: "0.4,0.75")
        --rm3: Comma-separated RM3 specs, e.g., "off,10-10-0.5" (default: "off,10-10-0.5")
        --auto-rm3: Enable automatic per-query RM3 (default: "true")
        --outdir: Output directory for results (required)

    Notes
    -----
    This script is designed to be run from the command line for batch
    evaluation and regression testing. It supports both fixed RM3 configurations
    and automatic per-query RM3 decisions. The output directory contains
    summary.json (all configurations), decisions.csv (per-query RM3 decisions
    when auto_rm3 is enabled), and run files (TSV format) for each configuration.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--bm25-index", type=Path, required=True)
    ap.add_argument("--queries", type=Path, required=True)
    ap.add_argument("--qrels", type=Path, required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--sweep-k1", type=str, default="0.9,1.2")
    ap.add_argument("--sweep-b", type=str, default="0.4,0.75")
    ap.add_argument("--rm3", type=str, default="off,10-10-0.5")
    ap.add_argument("--auto-rm3", type=str, default="true")
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()

    queries = _read_jsonl(args.queries)
    qrels = _read_qrels(args.qrels)
    k1s = [float(x) for x in args.sweep_k1.split(",") if x]
    bs = [float(x) for x in args.sweep_b.split(",") if x]
    rm3s = _parse_rm3_list(args.rm3)
    auto_rm3 = str(args.auto_rm3).strip().lower() in {"1", "true", "yes"}

    summary = sweep(
        index_dir=args.bm25_index,
        queries=queries,
        qrels=qrels,
        k=args.k,
        k1s=k1s,
        bs=bs,
        rm3s=rm3s,
        auto_rm3=auto_rm3,
        outdir=args.outdir,
    )
    print(json.dumps(summary["best"], indent=2))


if __name__ == "__main__":
    main()
