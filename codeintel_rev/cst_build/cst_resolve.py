# SPDX-License-Identifier: MIT
"""Stitch CST nodes to module summary rows and SCIP symbols."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from codeintel_rev.cst_build.cst_schema import NodeRecord, StitchCandidate, StitchInfo
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex


@dataclass(slots=True, frozen=True)
class ModuleRow:
    """Lightweight projection of a module.jsonl row."""

    module_id: str
    raw: Mapping[str, Any]


@dataclass(slots=True, frozen=True)
class StitchCounters:
    """Aggregate match counters used for index.json."""

    module_matches: int = 0
    scip_matches: int = 0

    def merge(self, other: StitchCounters) -> StitchCounters:
        """Return a new StitchCounters instance with merged totals.

        This method creates a new StitchCounters instance by adding the counter
        values from another instance to this instance's values. The method is
        used to aggregate match statistics across multiple files or collections.

        Parameters
        ----------
        other : StitchCounters
            Another StitchCounters instance whose values should be merged into
            this instance. The method adds other.module_matches and other.scip_matches
            to this instance's corresponding counters.

        Returns
        -------
        StitchCounters
            New StitchCounters instance with accumulated counter values. The
            module_matches and scip_matches fields contain the sum of this instance's
            and other's values. The original instances are not modified.
        """
        return StitchCounters(
            module_matches=self.module_matches + other.module_matches,
            scip_matches=self.scip_matches + other.scip_matches,
        )


@dataclass(slots=True, frozen=True)
class _SymbolCandidate:
    """Internal candidate structure for SCIP symbol matching.

    Attributes
    ----------
    symbol : str
        SCIP symbol identifier string (e.g., "scip-python python ...").
    line : int
        Line number where the symbol occurs (0-based).
    name_hint : str | None
        Extracted name hint from the symbol string (e.g., "function_name").
    qname_hint : str | None
        Extracted qualified name hint from the symbol string (e.g., "module.Class.method").
    """

    symbol: str
    line: int
    name_hint: str | None
    qname_hint: str | None


class SCIPResolver:
    """Best-effort matcher between CST spans and SCIP occurrences."""

    _DEF_KINDS: ClassVar[set[str]] = {
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Assign",
        "AnnAssign",
    }
    _USE_KINDS: ClassVar[set[str]] = {"Call", "Attribute", "Name"}

    def __init__(self, documents: Mapping[str, Document]) -> None:
        """Initialize SCIP resolver with document index.

        Parameters
        ----------
        documents : Mapping[str, Document]
            Mapping from file paths to SCIP Document objects containing symbol
            definitions and occurrences.
        """
        self._definition_index: dict[str, dict[int, list[_SymbolCandidate]]] = {}
        self._occurrence_index: dict[str, dict[int, list[_SymbolCandidate]]] = {}
        for path, document in documents.items():
            norm = _normalize_path(path)
            self._definition_index[norm] = {}
            self._occurrence_index[norm] = {}
            for occurrence in document.occurrences:
                if not occurrence.range:
                    continue
                candidate = _SymbolCandidate(
                    symbol=occurrence.symbol,
                    line=int(occurrence.range[0]),
                    name_hint=_symbol_name_hint(occurrence.symbol),
                    qname_hint=_symbol_qname_hint(occurrence.symbol),
                )
                target = (
                    self._definition_index[norm]
                    if "Definition" in (occurrence.roles or [])
                    else self._occurrence_index[norm]
                )
                target.setdefault(candidate.line, []).append(candidate)

    def match(
        self,
        node: NodeRecord,
        *,
        debug: bool = False,
    ) -> tuple[str, list[str], float, list[StitchCandidate] | None] | None:
        """Return (symbol, evidence, confidence, debug candidates) if matched.

        This method attempts to match a CST node record to a SCIP symbol by
        searching the symbol index for candidates matching the node's kind,
        name, and line position. The method uses best-effort matching with
        confidence scoring based on name hints and qualified names. When debug
        is enabled, returns candidate information for diagnostics.

        Parameters
        ----------
        node : NodeRecord
            CST node record to match against SCIP symbols. The node's kind,
            name, and line position are used to search for matching symbols.
            Only nodes with kinds in _DEF_KINDS or _USE_KINDS are processed.
        debug : bool, optional
            Flag indicating whether to include debug candidate information in
            the result (default: False). When True, the returned tuple includes
            a list of StitchCandidate objects for diagnostics. When False, the
            candidate list is None.

        Returns
        -------
        tuple[str, list[str], float, list[StitchCandidate] | None] | None
            Tuple containing:
            - symbol: Matched SCIP symbol identifier (e.g., "scip-python python ...")
            - evidence: List of evidence strings describing the match (e.g., ["name", "qname"])
            - confidence: Confidence score between 0.0 and 1.0 indicating match quality
            - debug candidates: Optional list of StitchCandidate objects when debug=True
            Returns None when no stitch candidate matched or node kind is not supported.
        """
        if node.kind not in (self._DEF_KINDS | self._USE_KINDS):
            return None
        index = self._definition_index if node.kind in self._DEF_KINDS else self._occurrence_index
        file_map = index.get(_normalize_path(node.path))
        if not file_map:
            return None
        base_line = node.span.start_line - 1
        candidates = _collect_candidates(file_map, base_line)
        if not candidates and node.name:
            candidates = [
                cand
                for line_candidates in file_map.values()
                for cand in line_candidates
                if cand.name_hint == node.name
            ]
        if not candidates:
            return None
        normalized_qnames = {_normalize_qname(q) for q in node.qnames}
        best = _select_best_candidate(node, base_line, normalized_qnames, candidates)
        if best is None:
            return None
        best_score, best_evidence, best_candidate, evaluated = best
        debug_candidates = None
        if debug:
            debug_candidates = [
                StitchCandidate(
                    symbol=item[2].symbol,
                    reason=",".join(item[1]) or "fallback",
                    score=round(item[0], 3),
                )
                for item in evaluated
            ]
        return best_candidate.symbol, best_evidence, best_score, debug_candidates


def load_modules(path: Path | None) -> dict[str, ModuleRow]:
    """Load modules.jsonl rows into a lookup keyed by normalized path.

    Parameters
    ----------
    path : Path | None
        File system path to the modules.jsonl file, or None to return empty dict.

    Returns
    -------
    dict[str, ModuleRow]
        Dictionary mapping normalized file paths to module row records.
    """
    if path is None or not path.exists():
        return {}
    payload = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    cursor = 0
    rows: dict[str, ModuleRow] = {}
    while cursor < len(payload):
        while cursor < len(payload) and payload[cursor].isspace():
            cursor += 1
        if cursor >= len(payload):
            break
        obj, offset = decoder.raw_decode(payload, cursor)
        cursor = offset
        if not isinstance(obj, dict):
            continue
        rel_path = _normalize_path(str(obj.get("path") or ""))
        if not rel_path:
            continue
        module_id = str(obj.get("module_id") or rel_path)
        rows[rel_path] = ModuleRow(module_id=module_id, raw=obj)
    return rows


def load_scip_index(path: Path | None) -> SCIPResolver | None:
    """Load the SCIP resolver when ``path`` exists.

    Parameters
    ----------
    path : Path | None
        File system path to the SCIP index file, or None to return None.

    Returns
    -------
    SCIPResolver | None
        SCIP resolver instance if the index file exists, otherwise None.
    """
    if path is None or not path.exists():
        return None
    index = SCIPIndex.load(path)
    return SCIPResolver(index.by_file())


def stitch_nodes(
    nodes: Iterable[NodeRecord],
    *,
    module_lookup: Mapping[str, ModuleRow],
    scip_resolver: SCIPResolver | None,
    debug: bool = False,
) -> tuple[list[NodeRecord], StitchCounters]:
    """Attach StitchInfo to ``nodes``.

    Parameters
    ----------
    nodes : Iterable[NodeRecord]
        Collection of node records to stitch.
    module_lookup : Mapping[str, ModuleRow]
        Dictionary mapping normalized paths to module row records.
    scip_resolver : SCIPResolver | None
        Optional SCIP resolver for symbol resolution.
    debug : bool, optional
        Whether to include debug candidate information. Defaults to False.

    Returns
    -------
    tuple[list[NodeRecord], StitchCounters]
        Tuple containing the list of stitched node records and stitch counters.
    """
    counters = StitchCounters()
    stitched: list[NodeRecord] = []
    for node in nodes:
        stitch = node.stitch or StitchInfo(evidence=[])
        current = StitchInfo(
            module_id=stitch.module_id,
            scip_symbol=stitch.scip_symbol,
            evidence=list(stitch.evidence),
            confidence=stitch.confidence,
            candidates=list(stitch.candidates) if stitch.candidates else None,
        )
        module_row = module_lookup.get(_normalize_path(node.path))
        if module_row:
            module_evidence = [*current.evidence, "module-path"]
            current = replace(current, module_id=module_row.module_id, evidence=module_evidence)
            counters = counters.merge(StitchCounters(module_matches=1))
        if scip_resolver:
            result = scip_resolver.match(node, debug=debug)
            if result:
                symbol, evidence, confidence, candidates = result
                scip_evidence = [*current.evidence, *evidence]
                current = replace(
                    current,
                    scip_symbol=symbol,
                    evidence=scip_evidence,
                    confidence=confidence,
                    candidates=list(candidates) if candidates is not None else None,
                )
                counters = counters.merge(StitchCounters(scip_matches=1))
        if current.evidence or current.module_id or current.scip_symbol:
            stitched.append(replace(node, stitch=current))
        else:
            stitched.append(node)
    return stitched, counters


def _normalize_path(path: str) -> str:
    """Normalize a file path to a POSIX-style relative path.

    Converts a file path to POSIX format (forward slashes) and removes leading
    "./" prefixes. Used for consistent path matching in symbol resolution.

    Parameters
    ----------
    path : str
        File path to normalize. May be absolute, relative, or contain Windows-style
        backslashes.

    Returns
    -------
    str
        Normalized POSIX-style path with forward slashes. Leading "./" prefixes
        are removed. Returns empty string if path normalizes to ".".
    """
    normalized = Path(path).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == ".":
        return ""
    return normalized


def _collect_candidates(
    file_map: Mapping[int, list[_SymbolCandidate]],
    base_line: int,
) -> list[_SymbolCandidate]:
    """Collect symbol candidates from adjacent lines.

    Searches for symbol candidates at the base line and its immediate neighbors
    (base_line - 1, base_line, base_line + 1) to handle slight line number
    mismatches between CST nodes and SCIP occurrences.

    Parameters
    ----------
    file_map : Mapping[int, list[_SymbolCandidate]]
        Dictionary mapping line numbers (0-based) to lists of symbol candidates
        found at those lines.
    base_line : int
        Base line number (0-based) to search around. Candidates are collected
        from base_line - 1, base_line, and base_line + 1.

    Returns
    -------
    list[_SymbolCandidate]
        List of all symbol candidates found at the base line and its immediate
        neighbors. Returns an empty list if no candidates are found or base_line
        is negative.
    """
    candidates: list[_SymbolCandidate] = []
    for delta in (-1, 0, 1):
        line = base_line + delta
        if line < 0:
            continue
        candidates.extend(file_map.get(line, []))
    return candidates


def _select_best_candidate(
    node: NodeRecord,
    base_line: int,
    normalized_qnames: set[str | None],
    candidates: list[_SymbolCandidate],
) -> (
    tuple[float, list[str], _SymbolCandidate, list[tuple[float, list[str], _SymbolCandidate]]]
    | None
):
    """Select the best matching symbol candidate from a list of candidates.

    Scores all candidates against the node's name and qualified names, filters
    out zero-score candidates, and returns the highest-scoring candidate along
    with all evaluated candidates for debugging.

    Parameters
    ----------
    node : NodeRecord
        CST node record to match against candidates. The node's name and qnames
        are used for scoring.
    base_line : int
        Base line number (0-based) of the node, used for span-based scoring.
    normalized_qnames : set[str | None]
        Set of normalized qualified names from the node, used for qname matching.
    candidates : list[_SymbolCandidate]
        List of symbol candidates to evaluate and rank.

    Returns
    -------
    tuple[float, list[str], _SymbolCandidate, list[tuple[float, list[str], _SymbolCandidate]]] | None
        Tuple containing:
        - Best score (float between 0.0 and 1.0)
        - Best evidence list (e.g., ["qname"] or ["name", "span"])
        - Best candidate (_SymbolCandidate)
        - All evaluated candidates with scores (for debugging)
        Returns None if no candidates score above 0.0.
    """
    evaluated: list[tuple[float, list[str], _SymbolCandidate]] = []
    for candidate in candidates:
        score, evidence = _score_candidate(
            node_name=node.name,
            node_line=base_line,
            normalized_qnames=normalized_qnames,
            candidate=candidate,
        )
        if score <= 0:
            continue
        evaluated.append((score, evidence, candidate))
    if not evaluated:
        return None
    evaluated.sort(key=lambda entry: entry[0], reverse=True)
    best_score, best_evidence, best_candidate = evaluated[0]
    return best_score, best_evidence, best_candidate, evaluated


def _symbol_name_hint(symbol: str) -> str | None:
    """Extract a simple name hint from a SCIP symbol string.

    Parses a SCIP symbol identifier to extract the leaf identifier name (e.g.,
    function name, class name) by removing path separators, call signatures,
    and other formatting tokens.

    Parameters
    ----------
    symbol : str
        SCIP symbol identifier string (e.g., "scip-python python pkg/module.py#Class.method()").

    Returns
    -------
    str | None
        Extracted name hint (e.g., "method") if parsing succeeds, or None if
        the symbol string cannot be parsed to extract a name.
    """
    tail = symbol.rsplit("/", 1)[-1]
    tail = tail.split("(", 1)[0]
    tail = tail.strip(".")
    for token in ("#", "`"):
        tail = tail.replace(token, ".")
    tail = tail.replace("..", ".")
    tail = tail.strip(".")
    if not tail:
        return None
    return tail.split(".")[-1]


def _symbol_qname_hint(symbol: str) -> str | None:
    """Extract a qualified name hint from a SCIP symbol string.

    Parses a SCIP symbol identifier to extract a fully qualified name (e.g.,
    "module.Class.method") by combining module path and symbol path components.

    Parameters
    ----------
    symbol : str
        SCIP symbol identifier string (e.g., "scip-python python `pkg/module.py`#Class.method()").

    Returns
    -------
    str | None
        Extracted qualified name hint (e.g., "pkg.module.Class.method") if parsing
        succeeds, or None if the symbol string cannot be parsed to extract a
        qualified name.
    """
    start = symbol.find("`")
    end = symbol.find("`", start + 1) if start != -1 else -1
    module_part = symbol[start + 1 : end] if start != -1 and end != -1 else None
    suffix = symbol[end + 1 :] if end != -1 else symbol
    suffix = suffix.replace("/", ".").replace("#", ".")
    suffix = suffix.split("(", 1)[0]
    suffix = suffix.strip(".")
    composed = f"{module_part}.{suffix}".strip(".") if module_part else suffix
    composed = composed.replace("..", ".")
    return composed or None


def _normalize_qname(qname: str | None) -> str | None:
    """Normalize a qualified name string for comparison.

    Removes whitespace and trims the qualified name to enable consistent
    matching between CST node qnames and SCIP symbol qname hints.

    Parameters
    ----------
    qname : str | None
        Qualified name string to normalize (e.g., "module.Class.method" or
        " module . Class . method "), or None.

    Returns
    -------
    str | None
        Normalized qualified name with whitespace removed, or None if qname
        is None or empty after normalization.
    """
    if not qname:
        return None
    return qname.strip().replace(" ", "")


def _score_candidate(
    *,
    node_name: str | None,
    node_line: int,
    normalized_qnames: set[str | None],
    candidate: _SymbolCandidate,
) -> tuple[float, list[str]]:
    """Score a symbol candidate against a CST node.

    Computes a confidence score (0.0 to 1.0) and evidence list based on how
    well the candidate matches the node's name, qualified names, and line position.
    Higher scores indicate stronger matches.

    Parameters
    ----------
    node_name : str | None
        Name of the CST node to match (e.g., "function_name").
    node_line : int
        Line number (0-based) of the CST node.
    normalized_qnames : set[str | None]
        Set of normalized qualified names from the CST node (e.g., {"module.Class.method"}).
    candidate : _SymbolCandidate
        Symbol candidate to score against the node.

    Returns
    -------
    tuple[float, list[str]]
        Tuple containing:
        - Score: float between 0.0 and 1.0 (1.0 = qname match, 0.8 = name+span match,
          0.6 = name match, 0.5 = span match, 0.0 = no match)
        - Evidence: list of match types (e.g., ["qname"], ["name", "span"], ["span"])
    """
    evidence: list[str] = []
    candidate_qname = _normalize_qname(candidate.qname_hint)
    normalized_qnames_clean = {entry for entry in normalized_qnames if entry}
    if candidate_qname and candidate_qname in normalized_qnames_clean:
        evidence.append("qname")
        return 1.0, evidence
    if node_name and candidate.name_hint and node_name == candidate.name_hint:
        if abs(candidate.line - node_line) <= 1:
            evidence.extend(["span", "name"])
            return 0.8, evidence
        evidence.append("name")
        return 0.6, evidence
    if abs(candidate.line - node_line) <= 1:
        evidence.append("span")
        return 0.5, evidence
    return 0.0, []
