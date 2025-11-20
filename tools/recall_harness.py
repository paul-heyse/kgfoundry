"""Recall harness for BM25 / RM3 sweeps."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path

from codeintel_rev.config import load_app_config
from codeintel_rev.config.api import AppConfig
from codeintel_rev.io.bm25_engine import BM25Engine, BM25Rm3Config, PyseriniBM25Backend
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params

LOGGER = logging.getLogger(__name__)

MIN_TREC_FIELDS = 4


@dataclass(slots=True, frozen=True)
class BM25SweepPlan:
    """Input artifacts describing a BM25 sweep experiment."""

    index_path: Path
    queries: list[tuple[str, str]]
    qrels: Mapping[str, set[str]]
    k_values: Sequence[int]
    grid: Sequence[tuple[float, float]]
    rm3_mode: str
    out: Path


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    """Load application configuration from environment or default.

    Returns
    -------
    AppConfig
        Loaded application configuration instance.
    """
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))


def _read_queries(path: Path) -> list[tuple[str, str]]:
    """Return query tuples (qid, query) from JSONL or CSV datasets.

    Parameters
    ----------
    path : Path
        Path to query file (JSONL or CSV format).

    Returns
    -------
    list[tuple[str, str]]
        List of ``(qid, query)`` tuples preserving file order.
    """
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            payloads = (json.loads(line) for line in handle if line.strip())
            return [
                (
                    str(payload.get("id") or payload.get("qid")),
                    str(payload["query"]),
                )
                for payload in payloads
            ]
    with path.open(encoding="utf-8", newline="") as handle:
        sniff = csv.Sniffer().sniff(handle.read(2048))
        handle.seek(0)
        reader = csv.DictReader(handle, dialect=sniff)
        fieldnames = reader.fieldnames or ()
        qfield = "query" if "query" in fieldnames else "text"
        qid_field = "id" if "id" in fieldnames else "qid"
        return [
            (str(row[qid_field]), str(row[qfield]))
            for row in reader
            if row.get(qid_field) and row.get(qfield)
        ]


def _read_qrels(path: Path) -> dict[str, set[str]]:
    """Return relevance judgements keyed by qid.

    Parameters
    ----------
    path : Path
        Path to relevance judgements file (TREC qrels or CSV format).

    Returns
    -------
    dict[str, set[str]]
        Mapping from query identifiers to sets of relevant document IDs.
    """
    qrels: dict[str, set[str]] = {}
    if path.suffix in {".trec", ".qrels"}:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                parts = line.strip().split()
                if len(parts) < MIN_TREC_FIELDS:
                    continue
                qid, _, doc_id, rel = parts[:MIN_TREC_FIELDS]
                if int(rel) > 0:
                    qrels.setdefault(qid, set()).add(str(doc_id))
        return qrels
    with path.open(encoding="utf-8", newline="") as handle:
        sniff = csv.Sniffer().sniff(handle.read(2048))
        handle.seek(0)
        reader = csv.DictReader(handle, dialect=sniff)
        for row in reader:
            qrels.setdefault(str(row["qid"]), set()).add(str(row["doc_id"]))
    return qrels


def _recall_at_k(pred: Sequence[str], gold: set[str], k: int) -> float:
    """Return binary recall@k for ``pred`` against ``gold``.

    Parameters
    ----------
    pred : Sequence[str]
        Predicted document IDs in ranked order.
    gold : set[str]
        Set of relevant (ground truth) document IDs.
    k : int
        Number of top results to consider.

    Returns
    -------
    float
        1.0 when at least one relevant document appears in the top-k results,
        otherwise 0.0.
    """
    if not gold or not pred:
        return 0.0
    top = pred[:k]
    return 1.0 if any(doc in gold for doc in top) else 0.0


def _mrr_at_k(pred: Sequence[str], gold: set[str], k: int) -> float:
    """Return reciprocal rank for the first relevant doc within top-k.

    Parameters
    ----------
    pred : Sequence[str]
        Predicted document IDs in ranked order.
    gold : set[str]
        Set of relevant (ground truth) document IDs.
    k : int
        Number of top results to consider.

    Returns
    -------
    float
        Reciprocal rank of the first relevant document within top-k, or 0.0.
    """
    if not gold:
        return 0.0
    for rank, doc in enumerate(pred[:k], start=1):
        if doc in gold:
            return 1.0 / float(rank)
    return 0.0


def _build_engine(
    index_path: Path,
    *,
    k1: float,
    b: float,
    rm3: BM25Rm3Config,
) -> BM25Engine:
    """Return a configured BM25 engine.

    Parameters
    ----------
    index_path : Path
        Path to BM25 index directory.
    k1 : float
        BM25 k1 parameter (term frequency saturation).
    b : float
        BM25 b parameter (length normalization).
    rm3 : BM25Rm3Config
        RM3 (relevance model) configuration.

    Returns
    -------
    BM25Engine
        Configured engine bound to ``index_path``.
    """
    backend = PyseriniBM25Backend(
        index_dir=index_path,
        k1=k1,
        b=b,
        rm3=rm3,
    )
    return BM25Engine(backend=backend)


def _prepare_rm3_config(app_config: AppConfig, rm3_mode: str) -> BM25Rm3Config:
    """Return RM3 configuration based on settings and sweep mode.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing BM25 and PRF settings.
    rm3_mode : str
        RM3 mode: "off", "on", or "auto".

    Returns
    -------
    BM25Rm3Config
        RM3 configuration capturing params, heuristics, and enablement flags.
    """
    bm25_settings = app_config.bm25
    prf_settings = app_config.index.prf
    rm3_params = RM3Params(
        fb_docs=bm25_settings.rm3_fb_docs,
        fb_terms=bm25_settings.rm3_fb_terms,
        orig_weight=bm25_settings.rm3_original_query_weight,
    )
    heuristics: RM3Heuristics | None = None
    if rm3_mode == "auto":
        head_terms: Iterable[str] | None = None
        if prf_settings.head_terms_csv:
            head_terms = [
                token.strip() for token in prf_settings.head_terms_csv.split(",") if token.strip()
            ]
        heuristics = RM3Heuristics(
            short_query_max_terms=prf_settings.short_query_max_terms,
            symbol_like_regex=prf_settings.symbol_like_regex,
            head_terms=head_terms,
            default_params=rm3_params,
        )
    return BM25Rm3Config(
        params=rm3_params,
        heuristics=heuristics,
        enable_rm3=rm3_mode in {"auto", "on"},
        auto_rm3=rm3_mode == "auto",
    )


def sweep_bm25(plan: BM25SweepPlan) -> None:
    """Run the sweep described by ``plan`` and emit CSV + recall metrics."""
    app_config = _cached_app_config()
    rm3_config = _prepare_rm3_config(app_config, plan.rm3_mode)
    max_k = max(plan.k_values)
    rows: list[dict[str, object]] = []
    for k1, b in plan.grid:
        engine = _build_engine(
            plan.index_path,
            k1=k1,
            b=b,
            rm3=rm3_config,
        )
        for qid, query in plan.queries:
            pairs = engine.search(query, k=max_k)
            doc_ids = [str(doc_id) for doc_id, _score in pairs]
            gold = plan.qrels.get(qid, set())
            metrics = _compute_metrics(doc_ids, gold, plan.k_values)
            rows.append(
                {
                    "qid": qid,
                    "query": query,
                    "k1": k1,
                    "b": b,
                    "rm3": plan.rm3_mode,
                    "results": len(doc_ids),
                    **metrics,
                }
            )
    _write_rows(plan.out, rows)
    _record_recall_metrics(rows, plan.k_values)


def _compute_metrics(
    doc_ids: Sequence[str],
    gold: set[str],
    k_values: Sequence[int],
) -> dict[str, float]:
    """Return recall and MRR metrics keyed by ``k``.

    Parameters
    ----------
    doc_ids : Sequence[str]
        Predicted document IDs in ranked order.
    gold : set[str]
        Set of relevant (ground truth) document IDs.
    k_values : Sequence[int]
        List of k values to compute metrics for (e.g., [1, 5, 10]).

    Returns
    -------
    dict[str, float]
        Mapping from metric name (e.g., ``recall@10``) to score.
    """
    metrics: dict[str, float] = {}
    for k in k_values:
        metrics[f"recall@{k}"] = _recall_at_k(doc_ids, gold, k)
        metrics[f"mrr@{k}"] = _mrr_at_k(doc_ids, gold, k)
    return metrics


def _write_rows(out: Path, rows: list[dict[str, object]]) -> None:
    """Write rows to CSV file with auto-detected fieldnames.

    Creates parent directories if needed and writes CSV with header
    row containing all unique keys from rows.

    Parameters
    ----------
    out : Path
        Output CSV file path.
    rows : list[dict[str, object]]
        List of dictionaries to write as CSV rows.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _record_recall_metrics(rows: list[dict[str, object]], k_values: Sequence[int]) -> None:
    """Log average recall metrics for each k value.

    Computes and logs average recall@k values across all rows for
    each k value in k_values.

    Parameters
    ----------
    rows : list[dict[str, object]]
        Rows containing recall@k metrics.
    k_values : Sequence[int]
        K values to compute averages for.
    """
    per_k: dict[int, list[float]] = {k: [] for k in k_values}
    for row in rows:
        for k in k_values:
            value = row.get(f"recall@{k}")
            if isinstance(value, (int, float)):
                per_k[k].append(float(value))
        for k, values in per_k.items():
            if values:
                average = sum(values) / len(values)
                LOGGER.info(
                    "Recall summary",
                    extra={
                        "k": k,
                        "average_recall": round(average, 4),
                        "samples": len(values),
                    },
                )


def main() -> None:
    """CLI entry point for running BM25 recall sweeps."""
    parser = argparse.ArgumentParser(description="BM25 recall harness")
    parser.add_argument("--bm25-index", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--k-list", default="10,25,50")
    parser.add_argument("--sweep-k1", default="0.9")
    parser.add_argument("--sweep-b", default="0.4")
    parser.add_argument(
        "--rm3",
        default="auto",
        choices=["auto", "on", "off"],
        help="RM3 mode: auto heuristics, always on, or disabled",
    )
    args = parser.parse_args()

    queries = _read_queries(args.queries)
    qrels = _read_qrels(args.qrels)
    k_values = [int(k) for k in args.k_list.split(",") if k]
    k1_values = [float(v) for v in args.sweep_k1.split(",") if v]
    b_values = [float(v) for v in args.sweep_b.split(",") if v]

    plan = BM25SweepPlan(
        index_path=args.bm25_index,
        queries=queries,
        qrels=qrels,
        k_values=k_values,
        grid=list(product(k1_values, b_values)),
        rm3_mode=args.rm3.lower(),
        out=args.out,
    )
    sweep_bm25(plan)


if __name__ == "__main__":
    main()
