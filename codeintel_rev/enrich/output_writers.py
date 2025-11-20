# SPDX-License-Identifier: MIT
"""Serialization helpers for enrichment artifacts (JSON/JSONL/Markdown)."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeintel_rev.enrich.meta_compat import (
    DefinitionRecord,
    ImportRecord,
    definition_entries,
    import_entries,
)

try:  # pragma: no cover - optional dependency
    import orjson
except ImportError:  # pragma: no cover - optional dependency
    orjson = None

try:  # pragma: no cover - optional dependency
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    from pyarrow.lib import ArrowException as _ArrowException
except ImportError:  # pragma: no cover - optional dependency
    pa = None
    ds = None
    pq = None
    _ArrowException = RuntimeError

ArrowExceptionType = _ArrowException if pa is not None else RuntimeError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pyarrow as pa_typing

    PaTable = pa_typing.Table
    PaSchema = pa_typing.Schema
else:  # pragma: no cover - runtime guard
    PaTable = Any
    PaSchema = Any

RowMapping = Mapping[str, object]
LOGGER = logging.getLogger(__name__)

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

    Raises
    ------
    RuntimeError
        Raised when deterministic serialization requires orjson but it is not installed.
    """
    if _ORJSON_JSONL_OPTS is not None:
        if orjson is None:  # pragma: no cover - defensive
            message = "orjson options configured without orjson installed"
            raise RuntimeError(message)
        return orjson.dumps(obj, option=_ORJSON_JSONL_OPTS)
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _resolve_dictionary_fields(table: PaTable, hints: Sequence[str] | None = None) -> list[str]:
    """Return dictionary-encoded columns present in ``table``.

    Parameters
    ----------
    table : PaTable
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


@dataclass(slots=True)
class WriterEnvConfig:
    """Configuration for resolving writer environment variables.

    Attributes
    ----------
    env_resolver : Callable[[str, str | None], str | None] | None, optional
        Optional function for resolving environment variable values. Takes
        variable name and default value, returns resolved value or None.
        If None, uses default environment variable lookup. Defaults to None.
    """

    env_resolver: Callable[[str, str | None], str | None] | None = None


_WRITER_ENV_STACK: list[WriterEnvConfig] = [WriterEnvConfig()]


@contextmanager
def override_writer_env(env_resolver: Callable[[str, str | None], str | None]) -> Iterator[None]:
    """Temporarily override the environment resolver for JSONL writers."""
    config = WriterEnvConfig(env_resolver=env_resolver)
    _WRITER_ENV_STACK.append(config)
    try:
        yield
    finally:
        _WRITER_ENV_STACK.pop()


def _resolve_env(key: str, default: str | None = None) -> str | None:
    """Resolve environment variable using current writer environment stack.

    This function resolves environment variables by checking the current writer
    environment stack for a custom resolver function. If a resolver is configured,
    it is used; otherwise, the function falls back to os.getenv.

    Parameters
    ----------
    key : str
        Environment variable name to resolve. The key is passed to the resolver
        function or os.getenv.
    default : str | None, optional
        Default value to return if the environment variable is not set. Passed
        to the resolver function or os.getenv. Defaults to None.

    Returns
    -------
    str | None
        Resolved environment variable value, or default if not set. Returns
        None if the variable is not set and default is None.

    Notes
    -----
    Environment resolution enables flexible configuration by allowing custom
    resolvers to override standard environment variable access. This supports
    testing with mock environments and runtime configuration overrides. The
    function uses the top of the writer environment stack, enabling nested
    context managers to override resolution behavior.
    """
    resolver = _WRITER_ENV_STACK[-1].env_resolver
    if resolver is not None:
        return resolver(key, default)
    return os.getenv(key, default)


def write_jsonl(
    path: str | Path,
    rows: Iterable[RowMapping],
    *,
    writer_version: str | None = None,
) -> int:
    """Write newline-delimited JSON records and return the row count.

    Parameters
    ----------
    path : str | Path
        Output file path for JSONL file.
    rows : Iterable[RowMapping]
        Iterable of row dictionaries to write.
    writer_version : str | None, optional
        Optional writer version identifier. None means use default or env var.
        Defaults to None.

    Returns
    -------
    int
        Number of rows that were emitted.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_version = (
        writer_version or _resolve_env(_JSONL_WRITER_ENV) or _JSONL_DEFAULT_VERSION
    ).lower()
    count = 0
    if resolved_version == _JSONL_V2 and _ORJSON_JSONL_OPTS is not None:
        with target.open("wb") as handle:
            for row in rows:
                payload = dict(row)
                handle.write(_dump_jsonl_bytes(payload))
                count += 1
        return count
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = dict(row)
            if resolved_version == _JSONL_V2:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            else:
                handle.write(_dump_json(payload))
            handle.write("\n")
            count += 1
    return count


def write_parquet(path: str | Path, rows: Iterable[RowMapping]) -> None:
    """Persist ``rows`` to Parquet, falling back to JSONL when PyArrow is missing."""
    records = [dict(row) for row in rows]
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
    rows: Iterable[RowMapping],
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
    rows : Iterable[RowMapping]
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
    records = [dict(row) for row in rows]
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
    table: PaTable,
    destination: Path,
    *,
    partitioning: Sequence[str] | None = None,
    dictionary_fields: Sequence[str] | None = None,
) -> None:
    """Write ``table`` to Parquet using dataset writer settings."""
    if pa is None or pq is None:
        return
    dictionary_columns = _resolve_dictionary_fields(table, dictionary_fields)
    if not partitioning or ds is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            table,
            destination,
            compression="zstd",
            use_dictionary=bool(dictionary_columns),
        )
        return
    destination.mkdir(parents=True, exist_ok=True)
    fmt = ds.ParquetFileFormat()
    file_options = fmt.make_write_options()
    file_options.update(compression="zstd")
    if dictionary_columns:
        file_options.update(use_dictionary=list(dictionary_columns))
    partition_fields = [
        table.schema.field(name) for name in partitioning if name in table.schema.names
    ]
    partition_schema = pa.schema(partition_fields)
    ds.write_dataset(
        data=table,
        format=fmt,
        base_dir=str(destination),
        partitioning=ds.partitioning(schema=partition_schema, flavor="hive"),
        file_options=file_options,
        existing_data_behavior="delete_matching",
    )


def write_parquet_or_jsonl(
    parquet_path: str | Path,
    jsonl_path: str | Path,
    rows: Iterable[RowMapping],
    *,
    schema: PaSchema | None = None,
) -> tuple[Path, int]:
    """Write rows to Parquet when possible, falling back to JSONL.

    Parameters
    ----------
    parquet_path : str | Path
        Preferred output path for Parquet format.
    jsonl_path : str | Path
        Fallback output path for JSONL format when Parquet is unavailable.
    rows : Iterable[RowMapping]
        Iterable of row dictionaries to write.
    schema : PaSchema | None, optional
        Optional PyArrow schema used when writing Parquet to enforce column
        ordering and types. Ignored when PyArrow is unavailable. Defaults to
        None.

    Returns
    -------
    tuple[Path, int]
        Tuple containing the path that was written and the number of emitted rows.
    """
    target = Path(parquet_path)
    fallback = Path(jsonl_path)
    materialized = [dict(row) for row in rows]
    if not materialized:
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text("", encoding="utf-8")
        return fallback, 0
    if pa is not None and pq is not None:
        try:
            table = pa.Table.from_pylist(materialized, schema=schema)
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, str(target))
            return target, len(materialized)
        except (ArrowExceptionType, OSError) as exc:  # pragma: no cover - fallback safety
            LOGGER.warning("Parquet write failed for %s: %s", target, exc)
    count = write_jsonl(fallback, materialized, writer_version=_JSONL_V2)
    return fallback, count


def _append_section(sections: list[str], title: str, lines: list[str]) -> None:
    r"""Append a Markdown section to the sections list if lines are present.

    This function conditionally appends a Markdown section header and content
    to a sections list. The section is only added if lines is non-empty,
    preventing empty sections in the output.

    Parameters
    ----------
    sections : list[str]
        List of Markdown lines to append to. The function appends a section
        header, content lines, and a blank line separator.
    title : str
        Section title to use for the Markdown header. The title is formatted
        as "## {title}\n".
    lines : list[str]
        List of content lines to include in the section. If empty, no section
        is appended. Lines are added verbatim after the header.

    Notes
    -----
    Section appending enables conditional Markdown generation by only including
    sections that have content. This prevents empty sections from cluttering
    the output and improves readability. The function adds a blank line after
    the section for proper Markdown formatting.
    """
    if not lines:
        return
    sections.append(f"## {title}\n")
    sections.extend(lines)
    sections.append("")


def _coerce_import_records(record: Mapping[str, object]) -> list[ImportRecord]:
    imports_field = record.get("imports")
    if not isinstance(imports_field, list):
        return []
    coerced: list[ImportRecord] = []
    for entry in imports_field:
        if not isinstance(entry, Mapping):
            continue
        module = entry.get("module")
        names = entry.get("names") or []
        aliases_obj = entry.get("aliases")
        alias_items = aliases_obj.items() if isinstance(aliases_obj, Mapping) else []
        normalized_names = tuple(str(name) for name in names if isinstance(name, str))
        normalized_aliases = {
            str(k): str(v) for k, v in alias_items if isinstance(k, str) and isinstance(v, str)
        }
        normalized_module = module if isinstance(module, str) or module is None else str(module)
        coerced.append(
            ImportRecord(
                module=normalized_module,
                names=normalized_names,
                aliases=normalized_aliases,
                is_star=bool(entry.get("is_star")),
                level=int(entry.get("level") or 0),
            )
        )
    return coerced


def _coerce_definition_records(record: Mapping[str, object]) -> list[DefinitionRecord]:
    defs_field = record.get("defs")
    if not isinstance(defs_field, list):
        return []
    coerced: list[DefinitionRecord] = []
    for entry in defs_field:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        kind = entry.get("kind")
        lineno = entry.get("lineno")
        if not isinstance(name, str) or not isinstance(kind, str):
            continue
        normalized_lineno = lineno if isinstance(lineno, int) else None
        coerced.append(DefinitionRecord(name=name, kind=kind, lineno=normalized_lineno))
    return coerced


def _format_imports(record: dict[str, object]) -> list[str]:
    """Format import statements from module record for Markdown output.

    This function extracts import information from a module record and formats
    it as a list of Markdown bullet points. Each import statement shows the
    module name and imported names, with special handling for star imports.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing import information. The record should
        have an "imports" key containing a list of import dictionaries.

    Returns
    -------
    list[str]
        List of formatted import statements as Markdown bullet points. Returns
        empty list if imports are missing, not a list, or empty. Each line
        follows the format "- from **{module}** import {names}".

    Notes
    -----
    Import formatting enables readable Markdown output by converting structured
    import data into human-friendly bullet points. The function handles star
    imports, absolute imports, and module imports gracefully, extracting names
    and module information from the record structure.
    """
    formatted: list[str] = []
    entries = _coerce_import_records(record) or import_entries(record)
    for entry in entries:
        names = list(entry.names)
        formatted.append(
            f"- from **{entry.module or '(absolute)'}** import "
            f"{', '.join(names) or '(module import)'}"
            f"{' *' if entry.is_star else ''}"
        )
    return formatted


def _format_definitions(record: dict[str, object]) -> list[str]:
    """Format symbol definitions from module record for Markdown output.

    This function extracts definition information from a module record and formats
    it as a list of Markdown bullet points. Each definition shows the kind (class,
    function, etc.), name, and line number.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing definition information. The record
        should have a "defs" key containing a list of definition dictionaries.

    Returns
    -------
    list[str]
        List of formatted definition statements as Markdown bullet points.
        Returns empty list if definitions are missing, not a list, or empty.
        Each line follows the format "- {kind}: `{name}` (line {lineno})".

    Notes
    -----
    Definition formatting enables readable Markdown output by converting structured
    definition data into human-friendly bullet points. The function extracts kind,
    name, and line number information, enabling users to quickly identify symbols
    and their locations in the source code.
    """
    formatted: list[str] = []
    records = _coerce_definition_records(record) or definition_entries(record)
    for definition in records:
        if definition.lineno is None:
            formatted.append(f"- {definition.kind}: `{definition.name}`")
        else:
            formatted.append(f"- {definition.kind}: `{definition.name}` (line {definition.lineno})")
    return formatted


def _format_graph_metrics(record: dict[str, object]) -> list[str]:
    """Format graph metrics from module record for Markdown output.

    This function extracts graph metrics (fan_in, fan_out, cycle_group) from
    a module record and formats them as Markdown bullet points. Graph metrics
    describe the module's position in the dependency graph.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing graph metrics. The record should
        have "fan_in", "fan_out", and/or "cycle_group" keys with integer values.

    Returns
    -------
    list[str]
        List of formatted graph metric statements as Markdown bullet points.
        Returns empty list if no graph metrics are present. Each line follows
        the format "- **{label}**: {value}".

    Notes
    -----
    Graph metric formatting enables readable Markdown output by converting
    structured graph data into human-friendly bullet points. The function
    extracts fan-in (dependencies), fan-out (dependents), and cycle group
    information, enabling users to understand module dependencies and structure.
    """
    lines: list[str] = []
    for label in ("fan_in", "fan_out", "cycle_group"):
        value = record.get(label)
        if isinstance(value, int):
            lines.append(f"- **{label}**: {value}")
    return lines


def _format_ownership(record: dict[str, object]) -> list[str]:
    """Format ownership and churn metrics from module record for Markdown output.

    This function extracts ownership information (owner, primary authors, bus factor)
    and churn metrics from a module record and formats them as Markdown bullet
    points. Ownership metrics describe code ownership and maintenance patterns.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing ownership and churn information.
        The record should have "owner", "primary_authors", "bus_factor", and
        churn keys (recent_churn_30, recent_churn_90, churn_30d, churn_90d).

    Returns
    -------
    list[str]
        List of formatted ownership and churn statements as Markdown bullet points.
        Returns empty list if no ownership information is present. Each line
        follows formats like "- owner: {owner}", "- primary authors: {authors}",
        "- bus factor: {value:.2f}", or "- {churn_label}: {value}".

    Notes
    -----
    Ownership formatting enables readable Markdown output by converting structured
    ownership and churn data into human-friendly bullet points. The function
    extracts owner, author, bus factor, and churn information, enabling users
    to understand code ownership patterns and maintenance activity.
    """
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
    """Format usage metrics from module record for Markdown output.

    This function extracts usage information (used_by_files, used_by_symbols)
    from a module record and formats them as Markdown bullet points. Usage
    metrics describe how widely the module is used across the codebase.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing usage information. The record should
        have "used_by_files" and/or "used_by_symbols" keys with integer values.

    Returns
    -------
    list[str]
        List of formatted usage statements as Markdown bullet points. Returns
        empty list if no usage information is present. Each line follows formats
        like "- used by files: {count}" or "- used by symbols: {count}".

    Notes
    -----
    Usage formatting enables readable Markdown output by converting structured
    usage data into human-friendly bullet points. The function extracts file
    and symbol usage counts, enabling users to understand module dependencies
    and usage patterns across the codebase.
    """
    lines: list[str] = []
    used_by_files = record.get("used_by_files")
    used_by_symbols = record.get("used_by_symbols")
    if isinstance(used_by_files, int):
        lines.append(f"- used by files: {used_by_files}")
    if isinstance(used_by_symbols, int):
        lines.append(f"- used by symbols: {used_by_symbols}")
    return lines


def _format_exports(record: dict[str, object]) -> list[str]:
    """Format declared exports (__all__) from module record for Markdown output.

    This function extracts declared exports from a module record and formats
    them as a comma-separated list. Declared exports are symbols listed in
    the module's __all__ attribute.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing export information. The record
        should have an "exports" key containing a list of export names.

    Returns
    -------
    list[str]
        List containing a single formatted export statement. Returns empty list
        if exports are missing, not a list, or empty. The statement is a
        comma-separated list of sorted export names.

    Notes
    -----
    Export formatting enables readable Markdown output by converting structured
    export data into a human-friendly comma-separated list. The function sorts
    export names alphabetically for consistent output, enabling users to quickly
    identify publicly exported symbols.
    """
    exports = record.get("exports") or []
    if isinstance(exports, list) and exports:
        names = ", ".join(sorted(name for name in exports if isinstance(name, str)))
        return [names]
    return []


def _format_exports_resolved(record: dict[str, object]) -> list[str]:
    """Format resolved star imports from module record for Markdown output.

    This function extracts resolved star import information from a module record
    and formats it as a list of Markdown bullet points. Resolved exports show
    which symbols are actually exported via star imports.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing resolved export information. The
        record should have an "exports_resolved" key containing a dictionary
        mapping origin modules to lists of exported names.

    Returns
    -------
    list[str]
        List of formatted resolved export statements as Markdown bullet points.
        Returns empty list if resolved exports are missing, not a dictionary,
        or empty. Each line follows the format "- from **{origin}** import {names}".

    Notes
    -----
    Resolved export formatting enables readable Markdown output by converting
    structured resolved export data into human-friendly bullet points. The
    function extracts origin modules and exported names, enabling users to
    understand which symbols are actually exported via star imports and their
    origins.
    """
    exports_resolved = record.get("exports_resolved") or {}
    lines: list[str] = []
    if isinstance(exports_resolved, Mapping):
        for origin, names in sorted(exports_resolved.items()):
            if isinstance(names, list):
                lines.append(f"- from **{origin}** import {', '.join(str(name) for name in names)}")
    return lines


def _format_reexports(record: dict[str, object]) -> list[str]:
    """Format re-export information from module record for Markdown output.

    This function extracts re-export information from a module record and formats
    it as a list of Markdown bullet points. Re-exports show symbols that are
    imported and then re-exported by the module.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing re-export information. The record
        should have a "reexports" key containing a dictionary mapping re-export
        names to metadata dictionaries with "from" and "symbol" keys.

    Returns
    -------
    list[str]
        List of formatted re-export statements as Markdown bullet points.
        Returns empty list if re-exports are missing, not a dictionary, or empty.
        Each line follows the format "- `{name}` ← **{origin}** ({symbol})".

    Notes
    -----
    Re-export formatting enables readable Markdown output by converting structured
    re-export data into human-friendly bullet points. The function extracts
    re-export names, origin modules, and symbol names, enabling users to understand
    which symbols are re-exported and their origins.
    """
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
    """Format documentation metrics from module record for Markdown output.

    This function extracts documentation quality metrics from a module record
    and formats them as Markdown bullet points. Documentation metrics include
    summary presence, parameter parity, and examples presence.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing documentation metrics. The record
        should have "doc_summary" and/or "doc_metrics" keys with summary text
        and metrics dictionary (has_summary, param_parity, examples_present).

    Returns
    -------
    list[str]
        List of formatted documentation metric statements as Markdown bullet
        points. Returns empty list if no documentation metrics are present.
        Each line follows formats like "- **summary**: {text}" or
        "- {metric_label}: yes/no".

    Notes
    -----
    Documentation metric formatting enables readable Markdown output by converting
    structured documentation quality data into human-friendly bullet points. The
    function extracts summary text and quality flags, enabling users to quickly
    assess documentation completeness and quality.
    """
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
    """Format type annotation metrics from module record for Markdown output.

    This function extracts type annotation metrics from a module record and
    formats them as Markdown bullet points. Typedness metrics include annotation
    ratios, untyped definitions, and type error counts.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing typedness metrics. The record should
        have "annotation_ratio" (with "params" and "returns" keys), "untyped_defs",
        and/or "type_errors" keys with numeric values.

    Returns
    -------
    list[str]
        List of formatted typedness statements as Markdown bullet points.
        Returns empty list if no typedness metrics are present. Each line
        follows formats like "- params annotated: {ratio:.2f}",
        "- returns annotated: {ratio:.2f}", "- untyped defs: {count}", or
        "- type errors: {count}".

    Notes
    -----
    Typedness formatting enables readable Markdown output by converting structured
    type annotation data into human-friendly bullet points. The function extracts
    annotation ratios, untyped definition counts, and type error counts, enabling
    users to quickly assess type coverage and type safety.
    """
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
    """Format side effect flags from module record for Markdown output.

    This function extracts side effect information from a module record and
    formats it as a list of Markdown bullet points. Side effects indicate
    operations that modify global state, perform I/O, or have external effects.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing side effect flags. The record
        should have a "side_effects" key containing a dictionary mapping
        side effect names to boolean values.

    Returns
    -------
    list[str]
        List of formatted side effect statements as Markdown bullet points.
        Returns ["- none detected"] if no side effects are present, or a list
        of side effect names if present. Each line follows the format
        "- {effect_name}" with underscores replaced by spaces.

    Notes
    -----
    Side effect formatting enables readable Markdown output by converting
    structured side effect data into human-friendly bullet points. The function
    extracts truthy side effect flags and formats them as readable names,
    enabling users to quickly identify modules with side effects.
    """
    flags = record.get("side_effects")
    if not isinstance(flags, Mapping):
        return []
    truthy = [name for name, value in flags.items() if bool(value)]
    if not truthy:
        return ["- none detected"]
    return [f"- {name.replace('_', ' ')}" for name in sorted(truthy)]


def _format_raises(record: dict[str, object]) -> list[str]:
    """Format exception information from module record for Markdown output.

    This function extracts exception information from a module record and formats
    it as a comma-separated list. Exception information shows which exceptions
    the module may raise.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing exception information. The record
        should have a "raises" key containing a list of exception names.

    Returns
    -------
    list[str]
        List containing a single formatted exception statement. Returns empty
        list if exceptions are missing, not a list, or empty. The statement
        is a comma-separated list of exception names.

    Notes
    -----
    Exception formatting enables readable Markdown output by converting structured
    exception data into a human-friendly comma-separated list. The function
    extracts exception names, enabling users to quickly identify which exceptions
    a module may raise.
    """
    raises = record.get("raises")
    if isinstance(raises, list):
        entries = [name for name in raises if isinstance(name, str)]
        if entries:
            return [", ".join(entries)]
    return []


def _format_complexity(record: dict[str, object]) -> list[str]:
    """Format complexity metrics from module record for Markdown output.

    This function extracts complexity metrics from a module record and formats
    them as Markdown bullet points. Complexity metrics include branches,
    cyclomatic complexity, and lines of code.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing complexity metrics. The record
        should have a "complexity" key containing a dictionary with "branches",
        "cyclomatic", and/or "loc" keys with integer values.

    Returns
    -------
    list[str]
        List of formatted complexity statements as Markdown bullet points.
        Returns empty list if complexity metrics are missing, not a dictionary,
        or empty. Each line follows the format "- {metric}: {value}".

    Notes
    -----
    Complexity formatting enables readable Markdown output by converting
    structured complexity data into human-friendly bullet points. The function
    extracts branch count, cyclomatic complexity, and lines of code, enabling
    users to quickly assess code complexity and maintainability.
    """
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
    """Format documentation coverage items from module record for Markdown output.

    This function extracts documentation coverage information for individual
    symbols from a module record and formats it as a list of Markdown bullet
    points. Each item shows symbol name, kind, and documentation quality metrics.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing documentation items. The record
        should have a "doc_items" key containing a list of item dictionaries
        with "name", "kind", "doc_summary", "doc_has_summary", "doc_param_parity",
        and "doc_examples_present" keys.
    limit : int, optional
        Maximum number of items to include in the output. Defaults to 10.
        Items beyond this limit are truncated.

    Returns
    -------
    list[str]
        List of formatted documentation item statements as Markdown bullet points.
        Returns empty list if documentation items are missing, not a list, or empty.
        Each line follows the format "- `{name}` ({kind}): {metrics} — {summary}".

    Notes
    -----
    Documentation item formatting enables readable Markdown output by converting
    structured documentation coverage data into human-friendly bullet points.
    The function extracts symbol names, kinds, documentation quality metrics,
    and summaries, enabling users to quickly assess documentation coverage for
    individual symbols. The limit parameter prevents overwhelming output for
    modules with many symbols.
    """
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
    """Format test coverage metrics from module record for Markdown output.

    This function extracts test coverage metrics from a module record and formats
    them as Markdown bullet points. Coverage metrics include line coverage and
    definition coverage ratios.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing coverage metrics. The record should
        have "covered_lines_ratio" and/or "covered_defs_ratio" keys with numeric
        values (typically floats between 0.0 and 1.0).

    Returns
    -------
    list[str]
        List of formatted coverage statements as Markdown bullet points.
        Returns empty list if no coverage metrics are present. Each line follows
        formats like "- lines covered: {ratio:.2%}" or "- defs covered: {ratio:.2%}".

    Notes
    -----
    Coverage formatting enables readable Markdown output by converting structured
    coverage data into human-friendly bullet points. The function extracts line
    and definition coverage ratios, formatting them as percentages, enabling
    users to quickly assess test coverage for the module.
    """
    lines: list[str] = []
    covered_lines = record.get("covered_lines_ratio")
    covered_defs = record.get("covered_defs_ratio")
    if isinstance(covered_lines, (int, float)):
        lines.append(f"- lines covered: {covered_lines:.2%}")
    if isinstance(covered_defs, (int, float)):
        lines.append(f"- defs covered: {covered_defs:.2%}")
    return lines


def _format_config_refs(record: dict[str, object]) -> list[str]:
    """Format configuration reference information from module record for Markdown output.

    This function extracts configuration reference information from a module record
    and formats it as a list of Markdown bullet points. Configuration references
    show which configuration files or settings the module depends on.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing configuration references. The record
        should have a "config_refs" key containing a list of reference strings.

    Returns
    -------
    list[str]
        List of formatted configuration reference statements as Markdown bullet
        points. Returns empty list if configuration references are missing, not
        a list, or empty. Each line follows the format "- {ref}".

    Notes
    -----
    Configuration reference formatting enables readable Markdown output by
    converting structured configuration reference data into human-friendly bullet
    points. The function extracts reference strings, enabling users to quickly
    identify which configuration files or settings the module depends on.
    """
    refs = record.get("config_refs")
    if not isinstance(refs, list) or not refs:
        return []
    return [f"- {ref}" for ref in refs if isinstance(ref, str)]


def _format_hotspot(record: dict[str, object]) -> list[str]:
    """Format hotspot score from module record for Markdown output.

    This function extracts hotspot score information from a module record and
    formats it as a Markdown bullet point. Hotspot scores indicate modules that
    are frequently changed and have high complexity, suggesting maintenance risk.

    Parameters
    ----------
    record : dict[str, object]
        Module record dictionary containing hotspot score. The record should
        have a "hotspot_score" key with a numeric value (typically a float).

    Returns
    -------
    list[str]
        List containing a single formatted hotspot score statement. Returns empty
        list if hotspot score is missing or not numeric. The statement follows
        the format "- score: {score:.2f}".

    Notes
    -----
    Hotspot formatting enables readable Markdown output by converting structured
    hotspot data into a human-friendly bullet point. The function extracts the
    hotspot score and formats it with two decimal places, enabling users to
    quickly identify modules with high maintenance risk.
    """
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
