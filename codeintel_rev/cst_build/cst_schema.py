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
    """Source span tracked for each node.

    Attributes
    ----------
    start_line : int
        Starting line number of the span (1-based).
    start_col : int
        Starting column number of the span (0-based).
    end_line : int
        Ending line number of the span (1-based).
    end_col : int
        Ending column number of the span (0-based, exclusive).
    """

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


@dataclass(slots=True, frozen=True)
class StitchInfo:
    """Join metadata linking nodes to module records and SCIP symbols.

    Attributes
    ----------
    module_id : str | None, optional
        Module identifier from the module records that this node is linked to.
        None if no module match was found. Defaults to None.
    scip_symbol : str | None, optional
        SCIP symbol identifier that this node is linked to. None if no SCIP
        symbol match was found. Defaults to None.
    evidence : list[str], optional
        List of evidence strings explaining why this node was linked to the
        module or SCIP symbol. Empty list if no evidence is available.
        Defaults to empty list.
    confidence : float | None, optional
        Confidence score for the stitching match (0.0 to 1.0). Higher values
        indicate stronger matches. None if confidence is not computed.
        Defaults to None.
    candidates : list[StitchCandidate] | None, optional
        List of candidate matches considered during stitching. Used for debugging
        and match quality analysis. None if candidates are not tracked.
        Defaults to None.
    """

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


@dataclass(slots=True, frozen=True)
class NodeRecord:
    """Single CST node row ready for serialization.

    Attributes
    ----------
    path : str
        File path relative to the repository root where this node occurs.
    node_id : str
        Unique identifier for this node within the file (e.g., "node_123").
    kind : str
        AST node kind (e.g., "FunctionDef", "ClassDef", "Call", "Name").
    name : str | None
        Name of the node if it has one (e.g., function name, class name).
        None for nodes without names.
    span : Span
        Source code span (line/column range) where this node occurs.
    text_preview : str | None
        Preview of the source code text for this node. None if preview is
        unavailable or too large.
    parents : list[str]
        List of parent node IDs representing the AST hierarchy. Empty list
        for root nodes.
    scope : str | None
        Qualified name of the scope containing this node (e.g., "module.Class.method").
        None if scope resolution failed.
    qnames : list[str]
        List of qualified names this node resolves to (e.g., ["builtins.str",
        "typing.Union"]). Empty list if resolution failed.
    doc : DocSnippet | None, optional
        Docstring snippet containing module and function/class docstrings.
        None if no docstring is available. Defaults to None.
    is_public : bool | None, optional
        Whether this node is part of the public API (not prefixed with _).
        None if public/private status is not determined. Defaults to None.
    decorators : list[str] | None, optional
        List of decorator names applied to this node. None if decorators are
        not tracked. Defaults to None.
    call_target_qnames : list[str] | None, optional
        List of qualified names of functions/methods called by this node.
        None if call targets are not tracked. Defaults to None.
    ann : str | None, optional
        Type annotation string for this node. None if no annotation is present.
        Defaults to None.
    imports : ImportMetadata | None, optional
        Import metadata for Import/ImportFrom nodes. None for non-import nodes.
        Defaults to None.
    stitch : StitchInfo | None, optional
        Stitching metadata linking this node to module records and SCIP symbols.
        None if stitching was not performed or no match was found. Defaults to None.
    errors : list[str] | None, optional
        List of error messages encountered during node processing. None if no
        errors occurred. Defaults to None.
    """

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


@dataclass(slots=True, frozen=True)
class CollectorStats:
    """Aggregated counters for provider usage.

    Attributes
    ----------
    files_indexed : int, optional
        Number of files successfully indexed. Defaults to 0.
    node_rows : int, optional
        Total number of node rows collected across all files. Defaults to 0.
    parse_errors : int, optional
        Number of files that failed to parse. Defaults to 0.
    qname_hits : int, optional
        Number of qualified name resolutions that succeeded. Defaults to 0.
    scope_resolved : int, optional
        Number of scope resolutions that succeeded. Defaults to 0.
    """

    files_indexed: int = 0
    node_rows: int = 0
    parse_errors: int = 0
    qname_hits: int = 0
    scope_resolved: int = 0

    def merge(self, other: CollectorStats) -> CollectorStats:
        """Return a new CollectorStats representing the merged totals.

        This method creates a new CollectorStats instance by adding the counter
        values from another instance to this instance's values. The method is
        used to aggregate collection statistics across multiple files or batches.

        Parameters
        ----------
        other : CollectorStats
            Another CollectorStats instance whose values should be merged into
            this instance. The method adds all counter fields (files_indexed,
            node_rows, parse_errors, qname_hits, scope_resolved) from other
            to this instance's corresponding counters.

        Returns
        -------
        CollectorStats
            New CollectorStats instance with accumulated counter values. All
            counter fields contain the sum of this instance's and other's values.
            The original instances are not modified.
        """
        return CollectorStats(
            files_indexed=self.files_indexed + other.files_indexed,
            node_rows=self.node_rows + other.node_rows,
            parse_errors=self.parse_errors + other.parse_errors,
            qname_hits=self.qname_hits + other.qname_hits,
            scope_resolved=self.scope_resolved + other.scope_resolved,
        )

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
    """Format a docstring snippet dictionary for serialization.

    Converts a DocSnippet dictionary (which uses "def_" as the key) to a
    normalized dictionary using "def" as the key (for JSON serialization).

    Parameters
    ----------
    doc : DocSnippet | None
        Docstring snippet dictionary containing optional "module" and "def_"
        keys, or None.

    Returns
    -------
    dict[str, str] | None
        Normalized dictionary with "module" and "def" keys (renamed from "def_"),
        or None if doc is None or empty after normalization.
    """
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
    """Conditionally assign an optional value to a payload dictionary.

    Adds a key-value pair to the payload dictionary only if the value is not None
    and (if allow_false is False) is truthy. Used for serialization to omit
    None and falsy values from JSON output.

    Parameters
    ----------
    payload : dict[str, object]
        Dictionary to update with the optional value. Modified in-place.
    key : str
        Dictionary key to assign the value to.
    value : object | None
        Value to assign if it passes the None and truthiness checks.
    allow_false : bool, optional
        If True, allows False values to be assigned (default: False). When False,
        falsy values (False, 0, empty strings, empty lists) are skipped along
        with None.

    Notes
    -----
    This function mutates the payload dictionary in-place. Values are only assigned
    if they are not None and (if allow_false=False) are truthy. This ensures
    that optional fields are omitted from serialized output when they have no
    meaningful value.
    """
    if value is None:
        return
    if not allow_false and not value:
        return
    payload[key] = value
