"""Data loading utilities for evaluation.

This module provides functions for loading queries, qrels, rankings,
and collections from TSV files.
"""

from __future__ import annotations

import pathlib
from collections import OrderedDict, defaultdict

from warp.utils.utils import print_message


def load_queries(queries_path: str | pathlib.Path) -> OrderedDict[str, str]:
    r"""Load queries from TSV file.

    Loads queries from tab-separated file with format: qid\tquery.

    Parameters
    ----------
    queries_path : str | pathlib.Path
        Path to queries TSV file.

    Returns
    -------
    OrderedDict[str, str]
        Dictionary mapping query IDs to query text.

    Raises
    ------
    ValueError
        If duplicate query IDs are found.
    """
    queries = OrderedDict()

    print_message("#> Loading the queries from", queries_path, "...")

    with pathlib.Path(queries_path).open(encoding="utf-8") as f:
        for line in f:
            qid, query, *_ = line.strip().split("\t")

            if qid in queries:
                msg = f"Query QID {qid!r} is repeated!"
                raise ValueError(msg)
            queries[qid] = query

    print_message("#> Got", len(queries), "queries. All QIDs are unique.\n")

    return queries


def load_qrels(
    qrels_path: str | pathlib.Path | None,
) -> OrderedDict[int, list[int]] | None:
    r"""Load query relevance judgments from TSV file.

    Loads qrels from tab-separated file with format: qid\t0\tpid\t1.

    Parameters
    ----------
    qrels_path : str | pathlib.Path | None
        Path to qrels TSV file (None returns None).

    Returns
    -------
    OrderedDict[int, list[int]] | None
        Dictionary mapping query IDs to lists of relevant passage IDs.

    Raises
    ------
    ValueError
        If qrels format is invalid (x != 0 or y != 1).
    """
    if qrels_path is None:
        return None

    print_message("#> Loading qrels from", qrels_path, "...")

    qrels = OrderedDict()
    with pathlib.Path(qrels_path).open(encoding="utf-8") as f:
        for line in f:
            qid, x, pid, y = map(int, line.strip().split("\t"))
            if x != 0:
                msg = f"Expected x=0 in qrels format, got x={x}"
                raise ValueError(msg)
            if y != 1:
                msg = f"Expected y=1 in qrels format, got y={y}"
                raise ValueError(msg)
            qrels[qid] = qrels.get(qid, [])
            qrels[qid].append(pid)

    for qid in qrels:
        qrels[qid] = list(set(qrels[qid]))

    avg_positive = round(sum(len(qrels[qid]) for qid in qrels) / len(qrels), 2)

    print_message(
        "#> Loaded qrels for",
        len(qrels),
        "unique queries with",
        avg_positive,
        "positives per query on average.\n",
    )

    return qrels


def load_top_k(
    top_k_path: str | pathlib.Path,
) -> tuple[
    OrderedDict[int, str], OrderedDict[int, list[str]], OrderedDict[int, list[int]]
]:
    r"""Load top-k documents per query from TSV file.

    Loads queries, documents, and passage IDs from tab-separated file
    with format: qid\tpid\tquery\tpassage.

    Parameters
    ----------
    top_k_path : str | pathlib.Path
        Path to top-k TSV file.

    Returns
    -------
    tuple[OrderedDict[int, str], OrderedDict[int, list[str]], OrderedDict[int, list[int]]]
        Tuple of (queries, top_k_docs, top_k_pids).

    Raises
    ------
    ValueError
        If query mismatch or duplicate PIDs found for queries.
    """
    queries = OrderedDict()
    top_k_docs = OrderedDict()
    top_k_pids = OrderedDict()

    print_message("#> Loading the top-k per query from", top_k_path, "...")

    with pathlib.Path(top_k_path).open(encoding="utf-8") as f:
        for line_idx, line in enumerate(f):
            if line_idx and line_idx % (10 * 1000 * 1000) == 0:
                pass

            qid, pid, query, passage = line.split("\t")
            qid, pid = int(qid), int(pid)

            if qid in queries and queries[qid] != query:
                msg = f"Query mismatch for qid {qid}: existing={queries[qid]!r}, new={query!r}"
                raise ValueError(msg)
            queries[qid] = query
            top_k_docs[qid] = top_k_docs.get(qid, [])
            top_k_docs[qid].append(passage)
            top_k_pids[qid] = top_k_pids.get(qid, [])
            top_k_pids[qid].append(pid)

    if not all(len(top_k_pids[qid]) == len(set(top_k_pids[qid])) for qid in top_k_pids):
        msg = "top_k_pids contains duplicate PIDs for some queries"
        raise ValueError(msg)

    ks = [len(top_k_pids[qid]) for qid in top_k_pids]

    print_message("#> max(ks) =", max(ks), ", avg(ks) =", round(sum(ks) / len(ks), 2))
    print_message(
        "#> Loaded the top-k per query for", len(queries), "unique queries.\n"
    )

    return queries, top_k_docs, top_k_pids


def _parse_top_k_line(line: str) -> tuple[int, int, list[str]]:
    """Parse a single line from top-k TSV file.

    Parameters
    ----------
    line : str
        TSV line to parse.

    Returns
    -------
    tuple[int, int, list[str]]
        Tuple of (qid, pid, rest_fields).

    Raises
    ------
    ValueError
        If rest fields count is invalid or label value is invalid.
    """
    qid, pid, *rest = line.strip().split("\t")
    qid, pid = int(qid), int(pid)

    if len(rest) not in {1, 2, 3}:
        msg = f"Expected 1-3 rest fields, got {len(rest)}"
        raise ValueError(msg)

    if len(rest) > 1:
        *_, label = rest
        label = int(label)
        if label not in {0, 1}:
            msg = f"label must be 0 or 1, got {label}"
            raise ValueError(msg)

    return qid, pid, rest


def _validate_top_k_data(
    top_k_pids: defaultdict[int, list[int]],
    top_k_positives: defaultdict[int, list[int]],
) -> None:
    """Validate top-k data for duplicates and consistency.

    Parameters
    ----------
    top_k_pids : defaultdict[int, list[int]]
        Top-k passage IDs per query.
    top_k_positives : defaultdict[int, list[int]]
        Positive passage IDs per query.

    Raises
    ------
    ValueError
        If duplicate PIDs are found in top_k_pids or top_k_positives.
    """
    if not all(len(top_k_pids[qid]) == len(set(top_k_pids[qid])) for qid in top_k_pids):
        msg = "top_k_pids contains duplicate PIDs for some queries"
        raise ValueError(msg)
    if not all(
        len(top_k_positives[qid]) == len(set(top_k_positives[qid]))
        for qid in top_k_positives
    ):
        msg = "top_k_positives contains duplicate PIDs for some queries"
        raise ValueError(msg)


def _normalize_top_k_positives(
    top_k_pids: defaultdict[int, list[int]],
    top_k_positives: defaultdict[int, list[int]],
) -> dict[int, set[int]] | None:
    """Normalize top-k positives and ensure consistency with top_k_pids.

    Parameters
    ----------
    top_k_pids : defaultdict[int, list[int]]
        Top-k passage IDs per query.
    top_k_positives : defaultdict[int, list[int]]
        Positive passage IDs per query.

    Returns
    -------
    dict[int, set[int]] | None
        Normalized positives as sets, or None if empty.

    Raises
    ------
    ValueError
        If length mismatches between top_k_pids and top_k_positives.
    """
    if len(top_k_positives) == 0:
        return None

    if len(top_k_pids) < len(top_k_positives):
        msg = (
            f"len(top_k_pids) ({len(top_k_pids)}) must be >= "
            f"len(top_k_positives) ({len(top_k_positives)})"
        )
        raise ValueError(msg)

    # Make them sets for fast lookups later
    top_k_positives_sets = {qid: set(top_k_positives[qid]) for qid in top_k_positives}

    # Fill missing queries with empty sets
    for qid in set.difference(set(top_k_pids.keys()), set(top_k_positives_sets.keys())):
        top_k_positives_sets[qid] = set()

    if len(top_k_pids) != len(top_k_positives_sets):
        msg = (
            f"len(top_k_pids) ({len(top_k_pids)}) must equal "
            f"len(top_k_positives_sets) ({len(top_k_positives_sets)})"
        )
        raise ValueError(msg)

    avg_positive = round(
        sum(len(top_k_positives_sets[qid]) for qid in top_k_positives_sets)
        / len(top_k_pids),
        2,
    )

    print_message(
        "#> Concurrently got annotations for",
        len(top_k_positives_sets),
        "unique queries with",
        avg_positive,
        "positives per query on average.\n",
    )

    return top_k_positives_sets


def load_top_k_pids(
    top_k_path: str | pathlib.Path, qrels: OrderedDict[int, list[int]] | None
) -> tuple[
    defaultdict[int, list[int]],
    OrderedDict[int, list[int]] | defaultdict[int, list[int]] | None,
]:
    r"""Load top-k passage IDs per query from TSV file.

    Loads passage IDs and optionally positive labels from tab-separated file
    with format: qid\tpid\t[optional_fields].

    Parameters
    ----------
    top_k_path : str | pathlib.Path
        Path to top-k TSV file.
    qrels : OrderedDict[int, list[int]] | None
        Optional qrels to merge (mutually exclusive with annotated file).

    Returns
    -------
    tuple[
        defaultdict[int, list[int]],
        OrderedDict[int, list[int]] | defaultdict[int, list[int]] | None,
    ]
        Tuple of (top_k_pids, top_k_positives).

    Raises
    ------
    ValueError
        If duplicate PIDs found, invalid label values, both qrels and
        annotated file provided, or length mismatches.
    """
    top_k_pids = defaultdict(list)
    top_k_positives = defaultdict(list)

    print_message("#> Loading the top-k PIDs per query from", top_k_path, "...")

    with pathlib.Path(top_k_path).open(encoding="utf-8") as f:
        for line_idx, line in enumerate(f):
            if line_idx and line_idx % (10 * 1000 * 1000) == 0:
                pass

            qid, pid, rest = _parse_top_k_line(line)
            top_k_pids[qid].append(pid)

            if len(rest) > 1:
                *_, label = rest
                label = int(label)
                if label >= 1:
                    top_k_positives[qid].append(pid)

    _validate_top_k_data(top_k_pids, top_k_positives)

    ks = [len(top_k_pids[qid]) for qid in top_k_pids]

    print_message("#> max(ks) =", max(ks), ", avg(ks) =", round(sum(ks) / len(ks), 2))
    print_message(
        "#> Loaded the top-k per query for", len(top_k_pids), "unique queries.\n"
    )

    top_k_positives_normalized = _normalize_top_k_positives(top_k_pids, top_k_positives)

    if qrels is not None and top_k_positives_normalized is not None:
        msg = "Cannot have both qrels and an annotated top-K file!"
        raise ValueError(msg)

    if top_k_positives_normalized is None:
        top_k_positives_normalized = qrels

    return top_k_pids, top_k_positives_normalized


def load_collection(collection_path: str | pathlib.Path) -> list[str]:
    r"""Load document collection from TSV file.

    Loads passages from tab-separated file with format: pid\tpassage\t[rest].
    Handles escaped newlines, carriage returns, and tabs.

    Parameters
    ----------
    collection_path : str | pathlib.Path
        Path to collection TSV file.

    Returns
    -------
    list[str]
        List of passage texts indexed by passage ID.

    Raises
    ------
    ValueError
        If passage IDs don't match line indices.
    """
    print_message("#> Loading collection...")

    collection = []

    with pathlib.Path(collection_path).open(encoding="utf-8") as f:
        for line_idx, line in enumerate(f):
            if line_idx % (1000 * 1000) == 0:
                pass

            pid, passage, *rest = line.strip("\n\r ").split("\t")
            passage = (
                passage.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
            )

            if pid != "id" and int(pid) != line_idx:
                msg = f"pid={pid}, line_idx={line_idx}"
                raise ValueError(msg)

            if len(rest) >= 1:
                title = rest[0]
                passage = title + " | " + passage

            collection.append(passage)

    return collection
