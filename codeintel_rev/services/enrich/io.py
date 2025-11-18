# SPDX-License-Identifier: MIT
"""Generic IO primitives shared across enrichment services."""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
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
    write_json,
    write_jsonl,
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
    sort_keys: bool


class _YamlDumpFn(Protocol):
    def __call__(
        self,
        data: Mapping[str, list[str]],
        **kwargs: Unpack[_YamlDumpKwargs],
    ) -> str: ...


def write_modules_json(
    out: Path,
    module_rows: Sequence[ModuleRecord | Mapping[str, Any]],
) -> Path:
    """Persist module rows to ``modules/modules.jsonl``.

    Returns
    -------
    Path
        Output path to ``modules/modules.jsonl``.
    """
    target = out / "modules" / "modules.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        target,
        [dict(row) if isinstance(row, Mapping) else asdict(row) for row in module_rows],
        writer_version="v2",
    )
    return target


def write_markdown_modules(out: Path, module_rows: Sequence[Mapping[str, Any]]) -> Path:
    """Emit Markdown module sheets.

    Returns
    -------
    Path
        Directory containing generated Markdown files.
    """
    modules_dir = out / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    for record in module_rows:
        path = record.get("path")
        if not isinstance(path, str):
            continue
        target = modules_dir / (Path(path).with_suffix(".md").name)
        write_markdown_module(target, dict(record))
    return modules_dir


def write_symbol_graph(out: Path, symbol_edges: list[tuple[str, str]]) -> Path:
    """Write symbol graph edges to JSON.

    Returns
    -------
    Path
        Path to the generated JSON file.
    """
    target = out / "graphs" / "symbol_graph.json"
    write_json(
        target,
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )
    return target


def write_tabular_records(parquet_path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist Parquet + JSONL pair for tabular analytics."""
    write_parquet(parquet_path, rows)
    write_jsonl(parquet_path.with_suffix(".jsonl"), rows)


def collect_ast_artifacts(
    root: Path,
    files: Iterable[Path],
) -> tuple[list[AstNodeRow], list[AstMetricsRow]]:
    """Collect AST nodes and metrics for ``files``.

    Returns
    -------
    tuple[list[AstNodeRow], list[AstMetricsRow]]
        Node/metric rows ready for serialization.
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
    """Persist AST artifacts to JSONL for portability."""
    write_jsonl(path, [row.as_record() for row in rows])


def write_tag_index(out: Path, tag_index: Mapping[str, list[str]]) -> Path | None:
    """Write tags/tags_index.yaml if YAML is available.

    Returns
    -------
    Path | None
        Path to the YAML file when emitted, otherwise ``None``.
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


__all__ = [
    "collect_ast_artifacts",
    "write_ast_jsonl",
    "write_markdown_modules",
    "write_modules_json",
    "write_symbol_graph",
    "write_tabular_records",
    "write_tag_index",
]
