# SPDX-License-Identifier: MIT
"""Dataclasses and helpers describing the CST dataset schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TypedDict

SCHEMA_VERSION = "cst/v1"


class DocSnippet(TypedDict, total=False):
    """Short docstring snippets recorded on nodes."""

    module: str
    def_: str

    def __repr__(self) -> str:  # pragma: no cover - diagnostic
        """Return string representation of the doc snippet.

        Returns
        -------
        str
            String representation showing the doc snippet dictionary.
        """
        return f"DocSnippet({dict(self)!r})"


class ImportMetadata(TypedDict, total=False):
    """Normalized import metadata for Import/ImportFrom nodes."""

    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int


class StitchCandidate(TypedDict, total=False):
    """Debug candidate entry for stitching heuristics."""

    symbol: str
    reason: str
    score: float


@dataclass(slots=True, frozen=True)
class Span:
    """Source span tracked for each node."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def to_dict(self) -> dict[str, list[int]]:
        """Return the serialized span payload.

        Returns
        -------
        dict[str, list[int]]
            Dictionary with "start" and "end" keys containing [line, column] lists.
        """
        return {
            "start": [self.start_line, self.start_col],
            "end": [self.end_line, self.end_col],
        }


@dataclass(slots=True)
class StitchInfo:
    """Join metadata linking nodes to module records and SCIP symbols."""

    module_id: str | None = None
    scip_symbol: str | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: float | None = None
    candidates: list[StitchCandidate] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation.

        Returns
        -------
        dict[str, object]
            Dictionary containing module_id, scip_symbol, evidence, and optionally
            confidence and candidates fields.
        """
        payload: dict[str, object] = {
            "module_id": self.module_id,
            "scip_symbol": self.scip_symbol,
            "evidence": list(self.evidence),
        }
        if self.confidence is not None:
            payload["confidence"] = round(self.confidence, 3)
        if self.candidates is not None:
            payload["candidates"] = self.candidates
        return payload


@dataclass(slots=True)
class NodeRecord:
    """Single CST node row ready for serialization."""

    path: str
    node_id: str
    kind: str
    name: str | None
    span: Span
    text_preview: str | None
    parents: list[str]
    scope: str | None
    qnames: list[str]
    doc: DocSnippet | None = None
    is_public: bool | None = None
    decorators: list[str] | None = None
    call_target_qnames: list[str] | None = None
    ann: str | None = None
    imports: ImportMetadata | None = None
    stitch: StitchInfo | None = None
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the node into the schema-compliant dict.

        Returns
        -------
        dict[str, object]
            Dictionary containing all node fields in the schema-compliant format,
            including path, node_id, kind, name, span, text_preview, parents, scope,
            qnames, and optional fields like doc, is_public, decorators, etc.
        """
        payload: dict[str, object] = {
            "path": self.path,
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name or "",
            "span": self.span.to_dict(),
            "text_preview": self.text_preview or "",
            "parents": self.parents,
            "scope": self.scope,
            "qnames": self.qnames,
        }
        _assign_optional(payload, "doc", _format_doc(self.doc))
        _assign_optional(payload, "is_public", self.is_public, allow_false=True)
        _assign_optional(payload, "decorators", self.decorators)
        _assign_optional(payload, "call_target_qnames", self.call_target_qnames)
        _assign_optional(payload, "ann", self.ann)
        _assign_optional(payload, "imports", self.imports)
        _assign_optional(payload, "errors", self.errors)
        if self.stitch:
            payload["stitch"] = self.stitch.to_dict()
        return payload


@dataclass(slots=True)
class CollectorStats:
    """Aggregated counters for provider usage."""

    files_indexed: int = 0
    node_rows: int = 0
    parse_errors: int = 0
    qname_hits: int = 0
    scope_resolved: int = 0

    def merge(self, other: CollectorStats) -> None:
        """Merge counters from ``other`` in place."""
        self.files_indexed += other.files_indexed
        self.node_rows += other.node_rows
        self.parse_errors += other.parse_errors
        self.qname_hits += other.qname_hits
        self.scope_resolved += other.scope_resolved

    def to_dict(self) -> dict[str, int]:
        """Return JSON payload for provider stats.

        Returns
        -------
        dict[str, int]
            Dictionary containing files_indexed, node_rows, parse_errors, qname_hits,
            and scope_resolved counters.
        """
        return asdict(self)


def _format_doc(doc: DocSnippet | None) -> dict[str, str] | None:
    if not doc:
        return None
    normalized: dict[str, str] = {}
    if "module" in doc:
        normalized["module"] = doc["module"]
    if "def_" in doc:
        normalized["def"] = doc["def_"]
    return normalized or None


def _assign_optional(
    payload: dict[str, object],
    key: str,
    value: object | None,
    *,
    allow_false: bool = False,
) -> None:
    if value is None:
        return
    if not allow_false and not value:
        return
    payload[key] = value
