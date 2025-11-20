"""GOID (Global Object Identifier) utilities for function span indexing.

This module provides functions for loading GOID registry data from Parquet files,
building function span indexes for efficient line-to-function lookups, and
managing function span metadata. Used by coverage analytics to map coverage
lines to their containing functions.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path


@dataclass(frozen=True)
class GOIDRow:
    """Materialized GOID registry entry."""

    goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str | None
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True)
class FunctionSpan:
    """Span metadata for a function or method."""

    goid_h128: str
    urn: str
    rel_path: str
    kind: str
    qualname: str
    start_line: int
    end_line: int


def _format_h128(raw: str | float) -> str:
    """Return a stable string representation of a GOID hash.

    Extended Summary
    ----------------
    Normalizes GOID hash values to string format for consistent handling.
    Converts numeric values to integer strings, preserving string values as-is.

    Parameters
    ----------
    raw : str | float
        GOID hash value in string or numeric format. May be a string
        representation or a numeric value from Parquet/JSON.

    Returns
    -------
    str
        Normalized string representation of the GOID hash. Numeric values
        are converted to integer strings, string values are returned unchanged.
    """
    if isinstance(raw, str):
        return raw
    try:
        return f"{int(raw)}"
    except (TypeError, ValueError):
        return str(raw)


def _rows_from_parquet(path: Path) -> Iterator[GOIDRow]:
    """Yield GOID rows from a Parquet registry.

    Extended Summary
    ----------------
    Reads GOID registry data from a Parquet file and yields GOIDRow instances.
    Uses DuckDB to query the Parquet file efficiently. Returns empty iterator
    if the file doesn't exist.

    Parameters
    ----------
    path : Path
        Path to Parquet file containing GOID registry data. File should contain
        columns: goid_h128, urn, repo, commit, rel_path, language, kind,
        qualname, start_line, end_line.

    Yields
    ------
    GOIDRow
        GOID registry row parsed from Parquet file. One row per function/class
        definition in the registry. Fields are normalized (h128 formatted,
        types coerced) before yielding.

    Notes
    -----
    Time O(n) where n is the number of rows; memory O(1) aside from DuckDB
    connection. Performs file I/O to read Parquet file. Thread-safe for
    separate DuckDB connections. Returns empty iterator immediately if file
    doesn't exist (no error raised).
    """
    if not path.exists():
        return
    con = duckdb.connect()
    query = """
        SELECT
            goid_h128,
            urn,
            repo,
            commit,
            rel_path,
            language,
            kind,
            qualname,
            start_line,
            end_line
        FROM read_parquet(?)
    """
    rows = con.execute(query, [str(path)]).fetchall()
    con.close()
    for (
        goid_h128,
        urn,
        repo,
        commit,
        rel_path,
        language,
        kind,
        qualname,
        start_line,
        end_line,
    ) in rows:
        yield GOIDRow(
            goid_h128=_format_h128(goid_h128),
            urn=str(urn),
            repo=str(repo),
            commit=str(commit),
            rel_path=str(rel_path),
            language=str(language),
            kind=str(kind),
            qualname=None if qualname is None else str(qualname),
            start_line=None if start_line is None else int(start_line),
            end_line=None if end_line is None else int(end_line),
        )


def load_goid_registry(enriched_dir: Path) -> list[GOIDRow]:
    """Load GOID registry entries from an enrichment output directory.

    Extended Summary
    ----------------
    Loads the complete GOID registry from the standard location in the
    enrichment output directory. Reads from goids.parquet file and returns
    all GOID rows as a list.

    Parameters
    ----------
    enriched_dir : Path
        Root directory of enrichment output. Must contain goid/goids.parquet
        file with GOID registry data.

    Returns
    -------
    list[GOIDRow]
        List of all GOID registry entries loaded from the Parquet file.
        Empty list if the file doesn't exist. Each entry contains function,
        class, and method metadata with GOID identifiers and location spans.

    Notes
    -----
    Time O(n) where n is the number of GOIDs; memory O(n) for the returned list.
    Performs file I/O to read Parquet file. Thread-safe for separate instances.
    """
    registry_path = enriched_dir / "goid" / "goids.parquet"
    return list(_rows_from_parquet(registry_path))


def build_function_span_index(goids: Iterable[GOIDRow]) -> dict[str, list[FunctionSpan]]:
    """Return rel_path -> sorted spans for function-like GOIDs.

    Extended Summary
    ----------------
    Builds an index mapping relative file paths to sorted lists of function
    spans. Filters GOIDs to include only functions and methods with valid
    line spans. Spans are sorted by start_line, then end_line for efficient
    lookup and deterministic ordering.

    Parameters
    ----------
    goids : Iterable[GOIDRow]
        Iterable of GOID registry entries. Only entries with kind="function"
        or kind="method" and valid start_line/end_line are included.

    Returns
    -------
    dict[str, list[FunctionSpan]]
        Mapping from relative file path to sorted list of FunctionSpan objects.
        Each span contains goid_h128, urn, rel_path, kind, qualname, start_line,
        and end_line. Spans within each file are sorted by (start_line, end_line).

    Notes
    -----
    Time O(n log n) where n is the number of function/method GOIDs (due to
    sorting); memory O(n) for the index. No I/O, pure computation. Thread-safe
    for separate instances. GOIDs without valid line spans are excluded.
    """
    by_path: dict[str, list[FunctionSpan]] = {}
    for goid in goids:
        if goid.kind not in {"function", "method"}:
            continue
        if goid.start_line is None or goid.end_line is None:
            continue
        span = FunctionSpan(
            goid_h128=goid.goid_h128,
            urn=goid.urn,
            rel_path=goid.rel_path,
            kind=goid.kind,
            qualname=goid.qualname or "",
            start_line=goid.start_line,
            end_line=goid.end_line,
        )
        by_path.setdefault(goid.rel_path, []).append(span)
    for spans in by_path.values():
        spans.sort(key=lambda span: (span.start_line, span.end_line))
    return by_path


def lookup_function_for_line(
    *,
    index_by_path: Mapping[str, Sequence[FunctionSpan]],
    rel_path: str,
    line: int,
) -> FunctionSpan | None:
    """Return innermost FunctionSpan containing a line.

    Extended Summary
    ----------------
    Finds the innermost function span that contains the specified line number.
    If multiple functions contain the line (e.g., nested functions), returns
    the one with the smallest span (most specific). Returns None if no
    function contains the line.

    Parameters
    ----------
    index_by_path : Mapping[str, list[FunctionSpan]]
        Function span index mapping relative paths to sorted span lists.
        Should be built via build_function_span_index().
    rel_path : str
        Relative file path to search within. Must match a key in index_by_path.
    line : int
        Line number to find containing function for. Must be >= 1.

    Returns
    -------
    FunctionSpan | None
        Innermost function span containing the line, or None if no function
        contains the line. The innermost span is the one with the smallest
        (end_line - start_line) among all spans containing the line.

    Notes
    -----
    Time O(m) where m is the number of functions in the file (linear scan);
    memory O(1). No I/O, pure computation. Thread-safe. Returns None if
    rel_path is not in the index or if no function spans contain the line.
    """
    spans = index_by_path.get(rel_path)
    if not spans:
        return None
    best: FunctionSpan | None = None
    for span in spans:
        if span.start_line <= line <= span.end_line and (
            best is None or (span.end_line - span.start_line) < (best.end_line - best.start_line)
        ):
            best = span
    return best


def build_qualname_index(goids: Iterable[GOIDRow]) -> dict[tuple[str, str], GOIDRow]:
    """Return mapping of (rel_path, qualname) to GOIDRow for functions.

    Extended Summary
    ----------------
    Builds an index mapping (relative_path, qualified_name) tuples to GOIDRow
    entries for function-like GOIDs. Used for looking up functions by their
    qualified name within a specific file. Only includes functions and methods
    with non-empty qualname values.

    Parameters
    ----------
    goids : Iterable[GOIDRow]
        Iterable of GOID registry entries. Only entries with kind="function"
        or kind="method" and non-empty qualname are included.

    Returns
    -------
    dict[tuple[str, str], GOIDRow]
        Mapping from (rel_path, qualname) tuple to GOIDRow. Each key uniquely
        identifies a function within a file. If multiple GOIDs share the same
        key, only the first encountered is stored.

    Notes
    -----
    Time O(n) where n is the number of function/method GOIDs; memory O(n)
    for the index. No I/O, pure computation. Thread-safe for separate instances.
    Functions without qualname are excluded from the index.
    """
    index: dict[tuple[str, str], GOIDRow] = {}
    for goid in goids:
        if goid.kind not in {"function", "method"}:
            continue
        qualname = goid.qualname
        if not qualname:
            continue
        key = (goid.rel_path, qualname)
        index.setdefault(key, goid)
    return index


def normalize_path(value: str | Path, repo_root: Path) -> str:
    """Return a stable repo-relative path string.

    Extended Summary
    ----------------
    Normalizes a file path to a stable repository-relative string format.
    Converts absolute paths to relative paths and handles path normalization
    for consistent path handling across the codebase.

    Parameters
    ----------
    value : str | Path
        File path to normalize. May be absolute or relative, string or Path.
    repo_root : Path
        Root directory of the repository. Used to compute relative paths
        from absolute paths.

    Returns
    -------
    str
        Normalized repository-relative path string. Paths are normalized
        using normalized_rel_path() helper which handles path resolution
        and relative path computation.

    Notes
    -----
    Time O(1); memory O(1) aside from path string storage. No I/O, pure
    path computation. Thread-safe. Delegates to normalized_rel_path() helper.
    """
    return normalized_rel_path(Path(value), repo_root)
