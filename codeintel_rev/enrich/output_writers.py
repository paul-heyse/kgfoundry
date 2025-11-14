# SPDX-License-Identifier: MIT
"""Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

try:  # pragma: no cover - optional dependency
    import orjson
except ImportError:  # pragma: no cover - optional dependency
    orjson = None

try:  # pragma: no cover - optional dependency
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - optional dependency
    pa = None
    ds = None
    pq = None


_JSONL_WRITER_ENV = "ENRICH_JSONL_WRITER"
_JSONL_V2 = "v2"
_JSONL_DEFAULT_VERSION = "v1"
_ORJSON_JSONL_OPTS = (
    orjson.OPT_SORT_KEYS | orjson.OPT_APPEND_NEWLINE if orjson is not None else None
)
_DEFAULT_DICT_FIELDS: tuple[str, ...] = (
    "path",
    "repo_path",
    "module_name",
    "language",
    "package",
    "tags",
    "owner",
)


def _dump_json(obj: object) -> str:
    """Serialize arbitrary objects to UTF-8 JSON with optional orjson accel.

    Parameters
    ----------
    obj : object
        Python object to serialize to JSON. Must be JSON-serializable (dicts,
        lists, strings, numbers, booleans, None). Complex objects are not
        supported.

    Returns
    -------
    str
        Pretty-printed JSON string with UTF-8 encoding.
    """
    if orjson is not None:
        try:
            return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8")
        except orjson.JSONEncodeError:
            pass
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _dump_jsonl_bytes(obj: object) -> bytes:
    """Serialize JSON rows for JSONL outputs with deterministic ordering.

    Parameters
    ----------
    obj : object
        Python object to serialize to JSON. The object must be JSON-serializable.
        If orjson is available, uses orjson for faster serialization. Otherwise,
        falls back to standard library json.

    Returns
    -------
    bytes
        UTF-8 encoded JSON bytes with a trailing newline. The output uses
        deterministic key ordering (sorted keys) for consistent serialization.
    """
    if _ORJSON_JSONL_OPTS is not None:
        return orjson.dumps(obj, option=_ORJSON_JSONL_OPTS)
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _resolve_dictionary_fields(table: pa.Table, hints: Sequence[str] | None = None) -> list[str]:
    """Return dictionary-encoded columns present in ``table``.

    Parameters
    ----------
    table : pa.Table
        PyArrow table to inspect for dictionary-encoded columns. The table's
        schema is checked to identify columns that use dictionary encoding.
    hints : Sequence[str] | None, optional
        Optional sequence of column names to check. If provided, only these
        columns are checked. If None, uses default dictionary field names.
        Defaults to None.

    Returns
    -------
    list[str]
        List of column names that are dictionary-encoded in the table. Returns
        an empty list if PyArrow is not available or if none of the hinted
        columns use dictionary encoding.
    """
    if pa is None:
        return []
    candidate_names = hints or _DEFAULT_DICT_FIELDS
    return [name for name in candidate_names if name in table.schema.names]


def write_json(path: str | Path, obj: object) -> None:
    """Write an object as pretty-printed JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_json(obj), encoding="utf-8")


def write_jsonl(path: str | Path, rows: Iterable[dict[str, object]]) -> None:
    """Write newline-delimited JSON records."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer_version = (os.getenv(_JSONL_WRITER_ENV) or _JSONL_DEFAULT_VERSION).lower()
    if writer_version == _JSONL_V2 and _ORJSON_JSONL_OPTS is not None:
        with target.open("wb") as handle:
            for row in rows:
                handle.write(_dump_jsonl_bytes(row))
        return
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            if writer_version == _JSONL_V2:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            else:
                handle.write(_dump_json(row))
            handle.write("\n")


def write_parquet(path: str | Path, rows: Iterable[dict[str, object]]) -> None:
    """Persist ``rows`` to Parquet, falling back to JSONL when PyArrow is missing."""
    records = list(rows)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if pa is None or pq is None:
        fallback = target if target.suffix == ".jsonl" else Path(f"{target}.jsonl")
        write_jsonl(fallback, records)
        return
    table = pa.Table.from_pylist(records)
    _write_dataset_table(table, target)


def write_parquet_dataset(
    path: str | Path,
    rows: Iterable[dict[str, object]],
    *,
    partitioning: Sequence[str],
    dictionary_fields: Sequence[str] | None = None,
) -> None:
    """Write records to a partitioned Parquet dataset directory.

    Parameters
    ----------
    path : str | Path
        Output directory path for the partitioned Parquet dataset. The directory
        will be created if it doesn't exist. If PyArrow is unavailable, falls back
        to writing a single JSONL file at this path.
    rows : Iterable[dict[str, object]]
        Iterable of dictionary records to write. Each dictionary represents a row
        in the dataset. Records are converted to a PyArrow table before writing.
    partitioning : Sequence[str]
        List of column names to use for partitioning. Each unique combination of
        values in these columns creates a separate Parquet file in a subdirectory.
        Must not be empty.
    dictionary_fields : Sequence[str] | None, optional
        Optional list of column names to use dictionary encoding for. Dictionary
        encoding can improve compression and query performance for columns with
        repeated values. If None, uses default dictionary fields. Defaults to None.

    Raises
    ------
    ValueError
        Raised when partitioning is empty. Partitioning columns are required
        for dataset writes to organize data into separate files.
    """
    records = list(rows)
    target = Path(path)
    if not partitioning:
        message = "Partitioning columns are required for dataset writes."
        raise ValueError(message)
    if pa is None or pq is None:
        fallback = target.with_suffix(".jsonl") if target.suffix else target / "dataset.jsonl"
        write_jsonl(fallback, records)
        return
    table = pa.Table.from_pylist(records)
    _write_dataset_table(
        table,
        target,
        partitioning=partitioning,
        dictionary_fields=dictionary_fields,
    )


def _write_dataset_table(
    table: pa.Table,
    destination: Path,
    *,
    partitioning: Sequence[str] | None = None,
    dictionary_fields: Sequence[str] | None = None,
) -> None:
    """Write ``table`` to Parquet using dataset writer settings."""
    if ds is None:
        pq.write_table(table, destination)
        return
    if table.num_rows == 0 and not partitioning:
        pq.write_table(table, destination)
        return
    fmt = ds.ParquetFileFormat()
    use_dictionary = _resolve_dictionary_fields(table, dictionary_fields)
    file_options = fmt.make_write_options(
        compression="zstd",
        use_dictionary=use_dictionary or None,
    )
    if partitioning:
        destination.mkdir(parents=True, exist_ok=True)
        base_dir = destination
        basename_template = "part-{i}.parquet"
        partitioning_descriptor = ds.partitioning(field_names=list(partitioning))
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        base_dir = destination.parent
        basename_template = destination.name
        partitioning_descriptor = None
    max_rows = max(1, table.num_rows)
    ds.write_dataset(
        data=table,
        format=fmt,
        base_dir=str(base_dir),
        partitioning=partitioning_descriptor,
        file_options=file_options,
        existing_data_behavior="delete_matching",
        basename_template=basename_template,
        max_rows_per_file=max_rows,
    )


def _append_section(sections: list[str], title: str, lines: list[str]) -> None:
    if not lines:
        return
    sections.append(f"## {title}\n")
    sections.extend(lines)
    sections.append("")


def _format_imports(record: dict[str, object]) -> list[str]:
    formatted: list[str] = []
    imports_obj = record.get("imports")
    if not isinstance(imports_obj, list):
        return formatted
    for entry in imports_obj:
        if not isinstance(entry, Mapping):
            continue
        names = entry.get("names") or []
        if not isinstance(names, list):
            names = [str(names)]
        formatted.append(
            f"- from **{entry.get('module') or '(absolute)'}** import "
            f"{', '.join(names) or '(module import)'}"
            f"{' *' if entry.get('is_star') else ''}"
        )
    return formatted


def _format_definitions(record: dict[str, object]) -> list[str]:
    formatted: list[str] = []
    defs_obj = record.get("defs")
    if not isinstance(defs_obj, list):
        return formatted
    for definition in defs_obj:
        if not isinstance(definition, Mapping):
            continue
        kind = definition.get("kind")
        name = definition.get("name")
        lineno = definition.get("lineno")
        if isinstance(kind, str) and isinstance(name, str) and isinstance(lineno, int):
            formatted.append(f"- {kind}: `{name}` (line {lineno})")
    return formatted


def _format_graph_metrics(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for label in ("fan_in", "fan_out", "cycle_group"):
        value = record.get(label)
        if isinstance(value, int):
            lines.append(f"- **{label}**: {value}")
    return lines


def _format_ownership(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    owner = record.get("owner")
    if isinstance(owner, str) and owner:
        lines.append(f"- owner: {owner}")
    authors = record.get("primary_authors")
    if isinstance(authors, list) and authors:
        joined = ", ".join(str(author) for author in authors if isinstance(author, str))
        if joined:
            lines.append(f"- primary authors: {joined}")
    bus_factor = record.get("bus_factor")
    if isinstance(bus_factor, (int, float)):
        lines.append(f"- bus factor: {float(bus_factor):.2f}")
    churn_keys = ("recent_churn_30", "recent_churn_90", "churn_30d", "churn_90d")
    for key in churn_keys:
        value = record.get(key)
        if isinstance(value, int):
            label = key.replace("_", " ")
            lines.append(f"- {label}: {value}")
    return lines


def _format_usage(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    used_by_files = record.get("used_by_files")
    used_by_symbols = record.get("used_by_symbols")
    if isinstance(used_by_files, int):
        lines.append(f"- used by files: {used_by_files}")
    if isinstance(used_by_symbols, int):
        lines.append(f"- used by symbols: {used_by_symbols}")
    return lines


def _format_exports(record: dict[str, object]) -> list[str]:
    exports = record.get("exports") or []
    if isinstance(exports, list) and exports:
        names = ", ".join(sorted(name for name in exports if isinstance(name, str)))
        return [names]
    return []


def _format_exports_resolved(record: dict[str, object]) -> list[str]:
    exports_resolved = record.get("exports_resolved") or {}
    lines: list[str] = []
    if isinstance(exports_resolved, Mapping):
        for origin, names in sorted(exports_resolved.items()):
            if isinstance(names, list):
                lines.append(f"- from **{origin}** import {', '.join(str(name) for name in names)}")
    return lines


def _format_reexports(record: dict[str, object]) -> list[str]:
    reexports = record.get("reexports") or {}
    lines: list[str] = []
    if isinstance(reexports, Mapping):
        for name, meta in sorted(reexports.items()):
            if not isinstance(meta, Mapping):
                continue
            origin = meta.get("from", "?")
            symbol = meta.get("symbol", "")
            suffix = f" ({symbol})" if symbol else ""
            lines.append(f"- `{name}` ← **{origin}**{suffix}")
    return lines


def _format_doc_metrics(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    summary = record.get("doc_summary")
    if isinstance(summary, str) and summary.strip():
        lines.append(f"- **summary**: {summary.strip()}")
    metrics = record.get("doc_metrics")
    if isinstance(metrics, Mapping):
        for key in ("has_summary", "param_parity", "examples_present"):
            value = metrics.get(key)
            if isinstance(value, bool):
                label = key.replace("_", " ")
                lines.append(f"- {label}: {'yes' if value else 'no'}")
    return lines


def _format_typedness(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    ratio = record.get("annotation_ratio")
    if isinstance(ratio, Mapping):
        params_ratio = ratio.get("params")
        returns_ratio = ratio.get("returns")
        if isinstance(params_ratio, (int, float)):
            lines.append(f"- params annotated: {params_ratio:.2f}")
        if isinstance(returns_ratio, (int, float)):
            lines.append(f"- returns annotated: {returns_ratio:.2f}")
    untyped = record.get("untyped_defs")
    if isinstance(untyped, int):
        lines.append(f"- untyped defs: {untyped}")
    type_errors = record.get("type_errors")
    if isinstance(type_errors, int):
        lines.append(f"- type errors: {type_errors}")
    return lines


def _format_side_effects(record: dict[str, object]) -> list[str]:
    flags = record.get("side_effects")
    if not isinstance(flags, Mapping):
        return []
    truthy = [name for name, value in flags.items() if bool(value)]
    if not truthy:
        return ["- none detected"]
    return [f"- {name.replace('_', ' ')}" for name in sorted(truthy)]


def _format_raises(record: dict[str, object]) -> list[str]:
    raises = record.get("raises")
    if isinstance(raises, list):
        entries = [name for name in raises if isinstance(name, str)]
        if entries:
            return [", ".join(entries)]
    return []


def _format_complexity(record: dict[str, object]) -> list[str]:
    complexity = record.get("complexity")
    if not isinstance(complexity, Mapping):
        return []
    lines: list[str] = []
    for key in ("branches", "cyclomatic", "loc"):
        value = complexity.get(key)
        if isinstance(value, int):
            lines.append(f"- {key}: {value}")
    return lines


def _format_doc_items(record: dict[str, object], limit: int = 10) -> list[str]:
    items = record.get("doc_items")
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for entry in items[:limit]:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        kind = entry.get("kind")
        summary = entry.get("doc_summary") or ""
        has_summary = entry.get("doc_has_summary")
        parity = entry.get("doc_param_parity")
        examples = entry.get("doc_examples_present")
        parts = []
        if isinstance(has_summary, bool):
            parts.append(f"summary={'yes' if has_summary else 'no'}")
        if isinstance(parity, bool):
            parts.append(f"params={'ok' if parity else 'mismatch'}")
        if isinstance(examples, bool):
            parts.append(f"examples={'yes' if examples else 'no'}")
        descriptor = ", ".join(parts)
        summary_text = f" — {summary}" if summary else ""
        lines.append(f"- `{name}` ({kind}): {descriptor}{summary_text}")
    return lines


def _format_coverage(record: dict[str, object]) -> list[str]:
    lines: list[str] = []
    covered_lines = record.get("covered_lines_ratio")
    covered_defs = record.get("covered_defs_ratio")
    if isinstance(covered_lines, (int, float)):
        lines.append(f"- lines covered: {covered_lines:.2%}")
    if isinstance(covered_defs, (int, float)):
        lines.append(f"- defs covered: {covered_defs:.2%}")
    return lines


def _format_config_refs(record: dict[str, object]) -> list[str]:
    refs = record.get("config_refs")
    if not isinstance(refs, list) or not refs:
        return []
    return [f"- {ref}" for ref in refs if isinstance(ref, str)]


def _format_hotspot(record: dict[str, object]) -> list[str]:
    score = record.get("hotspot_score")
    if not isinstance(score, (int, float)):
        return []
    return [f"- score: {score:.2f}"]


def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
    """Emit a human-friendly Markdown summary for a module record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = [f"# {record.get('path', 'Module')}\n"]
    docstring = record.get("docstring")
    if isinstance(docstring, str) and docstring.strip():
        sections.extend(["## Docstring\n", f"```\n{docstring.strip()}\n```\n"])
    _append_section(sections, "Imports", _format_imports(record))
    _append_section(sections, "Definitions", _format_definitions(record))
    _append_section(sections, "Graph Metrics", _format_graph_metrics(record))
    _append_section(sections, "Ownership", _format_ownership(record))
    _append_section(sections, "Usage", _format_usage(record))
    _append_section(sections, "Declared Exports (__all__)", _format_exports(record))
    _append_section(sections, "Resolved Star Imports", _format_exports_resolved(record))
    _append_section(sections, "Re-exports", _format_reexports(record))
    _append_section(sections, "Doc Health", _format_doc_metrics(record))
    _append_section(sections, "Typedness", _format_typedness(record))
    _append_section(sections, "Coverage", _format_coverage(record))
    _append_section(sections, "Config References", _format_config_refs(record))
    _append_section(sections, "Hotspot", _format_hotspot(record))
    _append_section(sections, "Side Effects", _format_side_effects(record))
    _append_section(sections, "Raises", _format_raises(record))
    _append_section(sections, "Complexity", _format_complexity(record))
    _append_section(sections, "Doc Coverage", _format_doc_items(record))

    tags = record.get("tags") or []
    if isinstance(tags, list) and tags:
        sections.append("## Tags\n")
        sections.append(", ".join(sorted(tag for tag in tags if isinstance(tag, str))) + "\n")
    errors = record.get("errors") or []
    if isinstance(errors, list) and errors:
        sections.append("## Parse Errors / Notes\n")
        sections.extend(f"- {err}" for err in errors if isinstance(err, str))
    target.write_text("\n".join(sections), encoding="utf-8")
