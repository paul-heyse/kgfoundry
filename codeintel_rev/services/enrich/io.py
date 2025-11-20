# SPDX-License-Identifier: MIT
"""Generic IO primitives shared across enrichment services."""

from __future__ import annotations

import ast
import json
import logging
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypedDict, Unpack, cast

from codeintel_rev.enrich.ast_indexer import (
    AstMetricsRow,
    AstNodeRow,
    collect_ast_nodes_from_tree,
    compute_ast_metrics,
    empty_metrics_row,
)
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.output_writers import (
    write_json as legacy_write_json,
)
from codeintel_rev.enrich.output_writers import (
    write_jsonl as legacy_write_jsonl,
)
from codeintel_rev.enrich.output_writers import (
    write_markdown_module,
    write_parquet,
)
from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None


class _YamlDumpKwargs(TypedDict, total=False):
    """Type definition for YAML dump keyword arguments.

    Attributes
    ----------
    sort_keys : bool, optional
        Whether to sort dictionary keys in output.
    """

    sort_keys: bool


class _YamlDumpFn(Protocol):
    """Protocol for YAML dump functions (e.g., yaml.safe_dump).

    Methods
    -------
    __call__(data, **kwargs)
        Serialize data to YAML string.
    """

    def __call__(
        self,
        data: Mapping[str, list[str]],
        **kwargs: Unpack[_YamlDumpKwargs],
    ) -> str: ...


def _row_payload(row: ModuleRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-ready mapping for ``row``.

    Parameters
    ----------
    row : ModuleRecord | Mapping[str, Any]
        Module record or dictionary to serialize.

    Returns
    -------
    dict[str, Any]
        Serialized mapping representing the module row.
    """
    return row.as_json_row() if isinstance(row, ModuleRecord) else dict(row)


def write_modules_json(
    out: Path,
    module_rows: Sequence[ModuleRecord | Mapping[str, Any]],
) -> Path:
    """Persist module rows to ``modules/modules.jsonl``.

    Parameters
    ----------
    out : Path
        Output directory where the modules subdirectory will be created.
    module_rows : Sequence[ModuleRecord | Mapping[str, Any]]
        Sequence of module records to write. Can be ModuleRecord objects or
        dictionaries.

    Returns
    -------
    Path
        Output path to ``modules/modules.jsonl``.
    """
    target = out / "modules" / "modules.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy_write_jsonl(target, [_row_payload(row) for row in module_rows], writer_version="v2")
    return target


def write_markdown_modules(out: Path, module_rows: Sequence[Mapping[str, Any]]) -> Path:
    """Emit Markdown module sheets.

    Parameters
    ----------
    out : Path
        Output directory where the modules subdirectory will be created.
    module_rows : Sequence[Mapping[str, Any]]
        Sequence of module record dictionaries to write as Markdown files.

    Returns
    -------
    Path
        Directory containing generated Markdown files.
    """
    modules_dir = out / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    for record in module_rows:
        payload = _row_payload(record)
        path = payload.get("path")
        if not isinstance(path, str):
            continue
        target = modules_dir / (Path(path).with_suffix(".md").name)
        write_markdown_module(target, payload)
    return modules_dir


def write_symbol_graph(out: Path, symbol_edges: list[tuple[str, str]]) -> Path:
    """Write symbol graph edges to JSON.

    Parameters
    ----------
    out : Path
        Output directory where the graphs subdirectory will be created.
    symbol_edges : list[tuple[str, str]]
        List of (symbol, file) tuples representing symbol-to-file edges.

    Returns
    -------
    Path
        Path to the generated JSON file.
    """
    target = out / "graphs" / "symbol_graph.json"
    legacy_write_json(
        target,
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )
    return target


def write_tabular_records(parquet_path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist Parquet + JSONL pair for tabular analytics.

    Parameters
    ----------
    parquet_path : Path
        Output path for the Parquet file. A JSONL file with the same name
        (different extension) will also be created.
    rows : list[dict[str, Any]]
        List of record dictionaries to write to both Parquet and JSONL formats.
    """
    write_parquet(parquet_path, rows)
    legacy_write_jsonl(parquet_path.with_suffix(".jsonl"), rows, writer_version="v2")


def collect_ast_artifacts(
    root: Path,
    files: Iterable[Path],
) -> tuple[list[AstNodeRow], list[AstMetricsRow]]:
    """Collect AST nodes and metrics for ``files``.

    Parameters
    ----------
    root : Path
        Repository root directory used for relative path computation.
    files : Iterable[Path]
        Iterable of Python file paths to parse and analyze.

    Returns
    -------
    tuple[list[AstNodeRow], list[AstMetricsRow]]
        Node/metric rows ready for serialization. Files that fail to parse
        or read are logged and skipped, with empty metrics rows added for
        parse failures.
    """
    node_rows: list[AstNodeRow] = []
    metric_rows: list[AstMetricsRow] = []
    for fp in files:
        rel = normalized_rel_path(fp, root)
        try:
            code = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            LOGGER.exception("Failed to read %s for AST emission", rel)
            continue
        try:
            tree = ast.parse(code, filename=rel, type_comments=True)
        except SyntaxError:
            LOGGER.exception("Failed to parse %s for AST emission", rel)
            metric_rows.append(empty_metrics_row(rel))
            continue
        node_rows.extend(collect_ast_nodes_from_tree(rel, tree))
        metric_rows.append(compute_ast_metrics(rel, tree))
    return node_rows, metric_rows


def write_ast_jsonl(path: Path, rows: Iterable[AstNodeRow | AstMetricsRow]) -> None:
    """Persist AST artifacts to JSONL for portability.

    Parameters
    ----------
    path : Path
        Output path for the JSONL file.
    rows : Iterable[AstNodeRow | AstMetricsRow]
        Iterable of AST node or metrics rows to serialize.
    """
    legacy_write_jsonl(path, [row.as_record() for row in rows])


def write_tag_index(out: Path, tag_index: Mapping[str, list[str]]) -> Path | None:
    """Write tags/tags_index.yaml if YAML is available.

    Parameters
    ----------
    out : Path
        Output directory where the tags subdirectory will be created.
    tag_index : Mapping[str, list[str]]
        Dictionary mapping tag names to lists of file paths that have that tag.

    Returns
    -------
    Path | None
        Path to the YAML file when emitted, otherwise ``None`` if YAML
        module is not available.
    """
    if yaml_module is None:
        return None
    safe_dump = getattr(yaml_module, "safe_dump", None)
    if not callable(safe_dump):
        return None
    dump_fn = cast("_YamlDumpFn", safe_dump)
    tags_path = out / "tags"
    tags_path.mkdir(parents=True, exist_ok=True)
    target = tags_path / "tags_index.yaml"
    target.write_text(dump_fn(tag_index, sort_keys=True), encoding="utf-8")
    return target


def atomic_write_text(path: Path, data: str) -> None:
    """Write text atomically via a temporary file swap.

    Parameters
    ----------
    path : Path
        Target file path where data should be written.
    data : str
        Text content to write to the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), encoding="utf-8"
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    """Write JSONL rows and return the number of emitted rows.

    Parameters
    ----------
    path : Path
        Output file path for JSONL file.
    rows : Iterable[Mapping[str, Any]]
        Iterable of row dictionaries to write.

    Returns
    -------
    int
        Number of encoded rows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


__all__ = [
    "atomic_write_text",
    "collect_ast_artifacts",
    "write_ast_jsonl",
    "write_jsonl",
    "write_markdown_modules",
    "write_modules_json",
    "write_symbol_graph",
    "write_tabular_records",
    "write_tag_index",
]
