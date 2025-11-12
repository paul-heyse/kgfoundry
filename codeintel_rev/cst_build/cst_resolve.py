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

        Returns
        -------
        StitchCounters
            Accumulated counters that include ``other``'s values.
        """
        return StitchCounters(
            module_matches=self.module_matches + other.module_matches,
            scip_matches=self.scip_matches + other.scip_matches,
        )


@dataclass(slots=True, frozen=True)
class _SymbolCandidate:
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

        Returns
        -------
        tuple[str, list[str], float, list[StitchCandidate] | None] | None
            Tuple containing symbol, evidence list, confidence score, and optional
            debug candidate info. Returns ``None`` when no stitch candidate matched.
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
