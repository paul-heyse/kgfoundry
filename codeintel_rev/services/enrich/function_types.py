# SPDX-License-Identifier: MIT
"""Per-function typedness and signature details."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

import libcst as cst
from libcst import MetadataWrapper

from codeintel_rev.ids.goid import RepoSnapshot
from codeintel_rev.services.enrich.function_analysis import (
    BaseFunctionVisitor,
    FunctionInfo,
    FunctionNode,
    collect_parameters,
)

IGNORED_NAMES = {"self", "cls"}


@dataclass(slots=True, frozen=True)
class FunctionTypesRow:
    """Typedness summary for a single function or method."""

    function_goid_h128: Decimal
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    total_params: int
    annotated_params: int
    unannotated_params: int
    param_typed_ratio: float
    has_return_annotation: bool
    return_type: str | None
    return_type_source: str
    type_comment: str | None
    param_types: dict[str, str | None]
    fully_typed: bool
    partial_typed: bool
    untyped: bool
    typedness_bucket: str
    typedness_source: str
    created_at: str


class FunctionTypesVisitor(BaseFunctionVisitor):
    """Collect typedness rows for all functions in a module."""

    def __init__(
        self,
        *,
        snapshot: RepoSnapshot,
        rel_path: str,
        module: cst.Module,
        created_at: str,
    ) -> None:
        super().__init__(snapshot=snapshot, rel_path=rel_path)
        self._module = module
        self._created_at = created_at
        self.rows: list[FunctionTypesRow] = []

    def process_function(self, info: FunctionInfo) -> None:
        if info.start_line <= 0 or info.end_line <= 0 or info.end_line < info.start_line:
            return
        param_types, counts = _collect_param_types(info.node, self._module)
        return_type = _annotation_string(info.node.returns, self._module)
        has_return_annotation = return_type is not None
        annotated_params = counts["annotated"]
        total_params = counts["total"]
        unannotated_params = max(total_params - annotated_params, 0)
        ratio = 1.0 if total_params == 0 else annotated_params / total_params
        fully_typed = has_return_annotation and annotated_params == total_params
        untyped = not has_return_annotation and annotated_params == 0
        partial_typed = not fully_typed and not untyped
        typedness_bucket = _typedness_bucket(fully_typed=fully_typed, untyped=untyped)
        typedness_source = _typedness_source(
            annotated_params=annotated_params,
            has_return_annotation=has_return_annotation,
            partial_typed=partial_typed,
        )
        self.rows.append(
            FunctionTypesRow(
                function_goid_h128=Decimal(info.goid.h128),
                urn=info.goid.urn,
                repo=info.goid.repo,
                commit=info.goid.commit,
                rel_path=info.goid.rel_path,
                language=info.goid.language,
                kind=info.kind,
                qualname=info.qualname,
                start_line=info.start_line,
                end_line=info.end_line,
                total_params=total_params,
                annotated_params=annotated_params,
                unannotated_params=unannotated_params,
                param_typed_ratio=ratio,
                has_return_annotation=has_return_annotation,
                return_type=return_type,
                return_type_source="annotation" if has_return_annotation else "unknown",
                type_comment=None,
                param_types=param_types,
                fully_typed=fully_typed,
                partial_typed=partial_typed,
                untyped=untyped,
                typedness_bucket=typedness_bucket,
                typedness_source=typedness_source,
                created_at=self._created_at,
            )
        )


def _collect_param_types(
    node: FunctionNode, module: cst.Module
) -> tuple[dict[str, str | None], dict[str, int]]:
    param_map: dict[str, str | None] = {}
    total = 0
    annotated = 0
    for param in collect_parameters(node):
        name = param.name.value
        ann = _annotation_string(param.annotation, module)
        param_map[name] = ann
        if name in IGNORED_NAMES:
            continue
        total += 1
        if ann is not None:
            annotated += 1
    return param_map, {"total": total, "annotated": annotated}


def _annotation_string(
    annotation: cst.Annotation | cst.MaybeSentinel | None, module: cst.Module
) -> str | None:
    if annotation is None or annotation is cst.MaybeSentinel.DEFAULT:
        return None
    return module.code_for_node(annotation.annotation)


def _typedness_bucket(*, fully_typed: bool, untyped: bool) -> str:
    if fully_typed:
        return "typed"
    if untyped:
        return "untyped"
    return "partial"


def _typedness_source(
    *,
    annotated_params: int,
    has_return_annotation: bool,
    partial_typed: bool,
) -> str:
    if annotated_params > 0 and has_return_annotation and not partial_typed:
        return "annotations"
    if annotated_params > 0 or has_return_annotation:
        return "mixed"
    return "unknown"


def build_function_types(
    *,
    repo: str,
    commit: str,
    rel_path: str,
    module: cst.Module,
    created_at: str | None = None,
) -> list[FunctionTypesRow]:
    """Return per-function typedness rows for ``module``.

    Parameters
    ----------
    repo : str
        Repository identifier for GOID generation.
    commit : str
        Commit hash for GOID generation.
    rel_path : str
        Repository-relative module path.
    module : cst.Module
        Parsed CST module to analyze.
    created_at : str | None, optional
        Optional ISO-8601 timestamp. When None, uses current UTC time.

    Returns
    -------
    list[FunctionTypesRow]
        Typedness rows for each discovered function or method.
    """
    snapshot = RepoSnapshot(repo=repo, commit=commit)
    wrapper = MetadataWrapper(module)
    timestamp = created_at or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    visitor = FunctionTypesVisitor(
        snapshot=snapshot,
        rel_path=rel_path,
        module=module,
        created_at=timestamp,
    )
    wrapper.visit(visitor)
    return visitor.rows


def prepare_function_types_parquet(
    rows: Sequence[FunctionTypesRow],
) -> list[dict[str, object]]:
    """Return Parquet-friendly payloads for typedness rows.

    Parameters
    ----------
    rows : Sequence[FunctionTypesRow]
        Typedness rows to serialize.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable dictionaries ready for Parquet writer.
    """
    return [asdict(row) for row in rows]


def prepare_function_types_json(
    rows: Sequence[FunctionTypesRow],
) -> list[dict[str, object]]:
    """Return JSON-serializable payloads for typedness rows.

    Parameters
    ----------
    rows : Sequence[FunctionTypesRow]
        Typedness rows to serialize.

    Returns
    -------
    list[dict[str, object]]
        Dictionaries with stringified GOID hashes for JSONL output.
    """
    serialized: list[dict[str, object]] = []
    for row in rows:
        record = asdict(row)
        record["function_goid_h128"] = str(record["function_goid_h128"])
        serialized.append(record)
    return serialized


__all__ = [
    "FunctionTypesRow",
    "build_function_types",
    "prepare_function_types_json",
    "prepare_function_types_parquet",
]
