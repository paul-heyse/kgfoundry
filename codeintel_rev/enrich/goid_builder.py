# SPDX-License-Identifier: MIT
"""GOID builder converting AST metadata into global identifiers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.ast_indexer import AstNodeRow
from codeintel_rev.enrich.graph.io import write_goid_crosswalk, write_goid_registry
from codeintel_rev.ids.goid import (
    GOID,
    CrosswalkRow,
    EntityDescriptor,
    GoidKind,
    RepoSnapshot,
    compute_goid,
)


def _kind_for_node(row: AstNodeRow) -> GoidKind | None:
    node_type = row.node_type
    if node_type in {"FunctionDef", "AsyncFunctionDef"}:
        if row.parent_qualname:
            return "method"
        return "function"
    if node_type == "ClassDef":
        return "class"
    return None


def _module_qualname(path: str) -> str:
    candidate = Path(path)
    if candidate.stem == "__init__":
        return ".".join(candidate.parent.parts)
    return ".".join(candidate.with_suffix("").parts)


def _chunk_id(path: str, start_line: int | None, end_line: int | None) -> str | None:
    if start_line is None:
        return None
    return f"{path}:{start_line}:{(end_line or start_line)}"


@dataclass(slots=True)
class GOIDArtifacts:
    """Materialized GOID registry and crosswalk records."""

    goids: list[GOID]
    crosswalks: list[CrosswalkRow]


class GOIDBuilder:
    """Builder producing GOID registry entries from AST rows."""

    def __init__(self, repo: str, commit: str, *, language: str = "python") -> None:
        self.snapshot = RepoSnapshot(repo=repo, commit=commit)
        self.language = language

    def build(self, ast_rows: Sequence[AstNodeRow]) -> GOIDArtifacts:
        """Build GOID registry and crosswalk artifacts from AST node rows.

        Parameters
        ----------
        ast_rows : Sequence[AstNodeRow]
            Sequence of AST node rows extracted from source files. Each row
            represents a code element (function, class, module) with metadata
            including path, line numbers, and qualified names.

        Returns
        -------
        GOIDArtifacts
            Container holding the generated GOID registry entries and crosswalk
            rows mapping GOIDs to AST nodes and chunk identifiers.

        Notes
        -----
        This method processes AST rows to generate GOIDs for modules and code
        elements. Module GOIDs are created for each unique path, and element
        GOIDs are created for functions, classes, and methods. The resulting
        artifacts include deduplicated GOIDs (by hash) and crosswalk entries
        linking GOIDs to AST node types and chunk identifiers.
        """
        goid_by_hash: dict[int, GOID] = {}
        crosswalks: list[CrosswalkRow] = []
        paths = {row.path for row in ast_rows if row.path}
        for path in sorted(paths):
            descriptor = EntityDescriptor(
                language=self.language,
                kind="module",
                rel_path=path,
                qualname=_module_qualname(path) or path.replace("/", "."),
                start_line=1,
                end_line=None,
            )
            module_goid = compute_goid(self.snapshot, descriptor)
            goid_by_hash.setdefault(module_goid.h128, module_goid)
            crosswalk_row: CrosswalkRow = {
                "goid_h128": module_goid.h128,
                "ast_node_type": "Module",
                "chunk_id": f"{path}:1:1",
                "evidence_json": {"path": path, "kind": "module"},
            }
            crosswalks.append(crosswalk_row)
        for row in ast_rows:
            kind = _kind_for_node(row)
            if kind is None:
                continue
            qual = row.qualname or row.name or row.path
            descriptor = EntityDescriptor(
                language=self.language,
                kind=kind,
                rel_path=row.path,
                qualname=qual,
                start_line=row.lineno,
                end_line=row.end_lineno,
            )
            goid = compute_goid(self.snapshot, descriptor)
            goid_by_hash.setdefault(goid.h128, goid)
            evidence: dict[str, Any] = {
                "path": row.path,
                "lineno": row.lineno,
                "end_lineno": row.end_lineno,
                "qualname": row.qualname,
                "node_type": row.node_type,
            }
            crosswalk_row: CrosswalkRow = {
                "goid_h128": goid.h128,
                "ast_node_type": row.node_type,
                "chunk_id": _chunk_id(row.path, row.lineno, row.end_lineno),
                "evidence_json": evidence,
            }
            crosswalks.append(crosswalk_row)
        return GOIDArtifacts(goids=list(goid_by_hash.values()), crosswalks=crosswalks)

    @staticmethod
    def write_artifacts(
        artifacts: GOIDArtifacts,
        out_dir: Path,
    ) -> tuple[Path, Path]:
        """Persist registry and crosswalk tables to disk.

        Parameters
        ----------
        artifacts : GOIDArtifacts
            GOID artifacts container holding registry entries and crosswalk
            rows to persist to disk.
        out_dir : Path
            Output directory where the "goid" subdirectory will be created
            to store registry and crosswalk files.

        Returns
        -------
        tuple[Path, Path]
            Tuple containing the paths to the written registry file and
            crosswalk file. Files are written as Parquet if available, with
            JSONL fallback.

        Notes
        -----
        This method creates a "goid" subdirectory in the output directory
        and writes two files: goids.parquet (or goids.jsonl) for the registry
        and goid_xwalk.parquet (or goid_xwalk.jsonl) for the crosswalk.
        Parent directories are created if they do not exist.
        """
        target_dir = out_dir / "goid"
        target_dir.mkdir(parents=True, exist_ok=True)
        goids_path = write_goid_registry(
            artifacts.goids,
            target_dir / "goids.parquet",
            jsonl_fallback=target_dir / "goids.jsonl",
        )
        crosswalk_path = write_goid_crosswalk(
            artifacts.crosswalks,
            target_dir / "goid_xwalk.parquet",
            jsonl_fallback=target_dir / "goid_xwalk.jsonl",
        )
        return goids_path, crosswalk_path


def run_goid_build(
    repo: str,
    commit: str,
    ast_rows: Sequence[AstNodeRow],
    out_dir: Path,
    *,
    language: str = "python",
) -> tuple[Path, Path]:
    """Build GOIDs from AST rows and persist artifacts to disk.

    Parameters
    ----------
    repo : str
        Repository identifier for GOID generation.
    commit : str
        Commit hash or version identifier for GOID generation.
    ast_rows : Sequence[AstNodeRow]
        Sequence of AST node rows to process into GOIDs.
    out_dir : Path
        Output directory where GOID artifacts will be written.
    language : str, optional
        Programming language identifier. Defaults to "python".

    Returns
    -------
    tuple[Path, Path]
        Tuple containing paths to the written registry file and crosswalk file.

    Notes
    -----
    This is a convenience function that creates a GOIDBuilder, builds artifacts
    from AST rows, and writes them to disk in a single call. Useful for simple
    workflows that don't need to inspect or modify artifacts before writing.
    """
    builder = GOIDBuilder(repo=repo, commit=commit, language=language)
    artifacts = builder.build(ast_rows)
    return builder.write_artifacts(artifacts, out_dir)
