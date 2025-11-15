"""SCIP index reader for extracting symbol definitions and ranges.

Parses index.scip (protobuf) or index.scip.json and extracts symbol definitions
with precise ranges for chunking and code intelligence.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    from collections.abc import Iterable


RANGE_TUPLE_LENGTH = 4


def _range_from_list(rng: Sequence[object]) -> tuple[int, int, int, int] | None:
    if len(rng) not in {RANGE_TUPLE_LENGTH, 3}:
        return None
    normalized: list[int] = []
    for value in rng:
        if not isinstance(value, (int, float)):
            return None
        normalized.append(int(value))
    if len(normalized) == RANGE_TUPLE_LENGTH:
        sl, sc, el, ec = normalized
    else:
        sl, sc, ec = normalized
        el = sl
    return (sl, sc, el, ec)


def _parse_occurrence(record: dict) -> tuple[str, tuple[int, int, int, int], int] | None:
    symbol = record.get("symbol", "")
    if not symbol:
        return None
    rng = record.get("range") or record.get("enclosingRange") or record.get("enclosing_range")
    range_tuple: tuple[int, int, int, int] | None = None
    if isinstance(rng, list):
        range_tuple = _range_from_list(rng)
    elif isinstance(rng, dict):
        start = rng.get("start", {})
        end = rng.get("end", {})
        range_tuple = (
            start.get("line", 0),
            start.get("character", 0),
            end.get("line", 0),
            end.get("character", 0),
        )
    if range_tuple is None:
        return None
    roles = record.get("symbolRoles") or record.get("symbol_roles") or 0
    if isinstance(roles, list):
        role_val = 0
        for r in roles:
            if r in {1, "DEFINITION"}:
                role_val |= 1
        roles = role_val
    return symbol, range_tuple, int(roles)


@dataclass(frozen=True)
class Range:
    """Source code range with line and character positions.

    Represents a contiguous region of source code using line and character
    coordinates. This matches the SCIP/LSP range format, which uses 0-indexed
    lines and characters (columns).

    Ranges are used to precisely identify symbol definitions and occurrences
    in source files. They can be converted to byte offsets for text extraction
    using the line_starts() helper function.

    Attributes
    ----------
    start_line : int
        Starting line number (0-indexed). The first line of a file is line 0.
        Used with start_character to identify the start position.
    start_character : int
        Starting character/column position (0-indexed) within start_line.
        Character 0 is the first character on the line. Used for precise
        positioning within a line.
    end_line : int
        Ending line number (0-indexed, inclusive). The range spans from
        start_line to end_line (inclusive).
    end_character : int
        Ending character/column position (0-indexed, exclusive) within end_line.
        The range includes characters from start_character up to (but not
        including) end_character. This matches LSP/SCIP convention.
    """

    start_line: int
    start_character: int
    end_line: int
    end_character: int


class Occurrence(msgspec.Struct, frozen=True):
    """Symbol occurrence in source code.

    Represents a single occurrence of a symbol (definition, reference, etc.)
    within a source file. Occurrences are extracted from SCIP indexes and
    used to build symbol-to-location mappings.

    The range is stored as a tuple for efficient serialization, matching the
    SCIP JSON format. The roles field uses bit flags to indicate the type
    of occurrence (definition, reference, etc.).

    Attributes
    ----------
    symbol : str
        SCIP symbol identifier string. Format depends on language (e.g.,
        "python kgfoundry.core#Function.main" for Python). Used to link
        occurrences to symbol definitions.
    range : tuple[int, int, int, int]
        Source code range as (start_line, start_character, end_line, end_character).
        All values are 0-indexed. The range is inclusive at start, exclusive
        at end (matching LSP convention). Stored as tuple for JSON compatibility.
    roles : int
        Role bitmask indicating the type of occurrence. Bit 0 (LSB) = Definition,
        other bits indicate references, implementations, etc. Defaults to 0
        (unknown/unspecified role). Use bitwise AND to check roles:
        `(occ.roles & 1) != 0` checks for definition.
    """

    symbol: str
    range: tuple[int, int, int, int]
    roles: int = 0


class Document(msgspec.Struct, frozen=True):
    """SCIP document representing a source file.

    A Document represents a single source file that has been indexed by SCIP.
    It contains all symbol occurrences (definitions and references) found in
    that file, along with metadata about the file's language and path.

    Documents are immutable and designed for efficient serialization to/from
    JSON. They are the building blocks of a SCIPIndex.

    Attributes
    ----------
    relative_path : str
        File path relative to the repository root. This matches the path format
        used in SCIP indexes and is used to locate files during indexing and
        search. Should use forward slashes even on Windows.
    language : str
        Programming language identifier (e.g., "python", "typescript", "go").
        Used to filter files by language and apply language-specific processing.
        Matches SCIP language identifiers.
    occurrences : tuple[Occurrence, ...]
        All symbol occurrences found in this document. Includes both definitions
        (where symbols are defined) and references (where symbols are used).
        Empty tuple if no symbols found. Stored as tuple for immutability and
        efficient serialization.
    """

    relative_path: str
    language: str
    occurrences: tuple[Occurrence, ...] = ()


class SCIPIndex(msgspec.Struct, frozen=True):
    """SCIP index containing all indexed documents.

    The root structure of a SCIP index, containing all documents (source files)
    that have been indexed. This is the top-level object returned by parse_scip_json()
    and is used to extract symbol definitions and build the code intelligence index.

    The index is immutable and can be safely shared across threads. It's designed
    for efficient serialization to/from JSON format.

    Attributes
    ----------
    documents : tuple[Document, ...]
        All indexed documents (source files) in the repository. Each document
        contains symbol occurrences for one file. Empty tuple if no documents
        indexed. Documents are typically sorted by relative_path for consistent
        ordering.
    """

    documents: tuple[Document, ...] = ()


@dataclass(frozen=True)
class SymbolDef:
    """Extracted symbol definition with location information.

    Represents a single symbol definition extracted from a SCIP index. This is
    the processed form of an Occurrence with role=Definition, converted to
    a more convenient format for chunking and indexing.

    SymbolDef objects are used by the cAST chunker to create structure-aware
    chunks that respect symbol boundaries. They're also used for symbol search
    and "go to definition" functionality.

    Attributes
    ----------
    symbol : str
        SCIP symbol identifier string (e.g., "python kgfoundry.core#Function.main").
        Uniquely identifies the symbol across the entire codebase. Used for
        cross-references and symbol search.
    path : str
        File path where this symbol is defined. Typically a relative path from
        the repository root, matching the Document.relative_path format.
    range : Range
        Precise source code range where the symbol is defined. Includes start
        and end line/character positions. Used for exact location navigation
        and text extraction.
    language : str
        Programming language of the file containing this symbol (e.g., "python").
        Used for language-specific processing and filtering. Matches the
        Document.language value.
    """

    symbol: str
    path: str
    range: Range
    language: str


def parse_scip_json(json_path: Path) -> SCIPIndex:
    """Parse SCIP index from JSON export.

    Reads and parses a SCIP index that has been exported to JSON format.
    The JSON format is more convenient than the binary protobuf format for
    Python processing and debugging.

    The function handles various SCIP JSON formats (different versions may have
    slightly different field names) and converts them to the canonical SCIPIndex
    structure. It extracts documents and their occurrences, converting range
    formats (array vs object) to the standard tuple format.

    Parameters
    ----------
    json_path : Path
        Path to the index.scip.json file. This is typically generated by
        exporting a binary SCIP index using the SCIP CLI tool.

    Returns
    -------
    SCIPIndex
        Parsed SCIP index containing all documents and their symbol occurrences.
        The index is ready for use with extract_definitions() and other processing
        functions.

    Notes
    -----
    The function gracefully handles missing or malformed data:
    - Documents without relative_path are skipped
    - Occurrences without symbols are skipped
    - Invalid range formats are skipped
    - Missing fields use empty defaults

    The function does not raise exceptions for parsing errors - it silently
    skips invalid entries to ensure robust processing of partial indexes.
    """
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    documents = []
    for doc_data in data.get("documents", []):
        relative_path = doc_data.get("relativePath") or doc_data.get("relative_path", "")
        language = doc_data.get("language", "")

        occurrences = []
        for occ in doc_data.get("occurrences", []):
            parsed = _parse_occurrence(occ)
            if parsed is None:
                continue
            symbol, range_tuple, roles = parsed
            occurrences.append(Occurrence(symbol=symbol, range=range_tuple, roles=roles))

        if relative_path:
            documents.append(
                Document(
                    relative_path=relative_path,
                    language=language,
                    occurrences=tuple(occurrences),
                )
            )

    return SCIPIndex(documents=tuple(documents))


def extract_definitions(index: SCIPIndex) -> Iterable[SymbolDef]:
    """Extract symbol definitions from SCIP index.

    Yields definition occurrences (roles & 1 != 0) or first occurrence per symbol
    as fallback.

    Parameters
    ----------
    index : SCIPIndex
        Parsed SCIP index.

    Yields
    ------
    SymbolDef
        Symbol definition with range.
    """
    for doc in index.documents:
        # Track first occurrence per symbol as fallback
        first_by_symbol: dict[str, Occurrence] = {}
        definitions: list[SymbolDef] = []

        for occ in doc.occurrences:
            is_def = (occ.roles & 1) != 0
            if is_def:
                sl, sc, el, ec = occ.range
                definitions.append(
                    SymbolDef(
                        symbol=occ.symbol,
                        path=doc.relative_path,
                        range=Range(sl, sc, el, ec),
                        language=doc.language,
                    )
                )
            if occ.symbol not in first_by_symbol:
                first_by_symbol[occ.symbol] = occ

        # Yield definitions or fallback to first occurrences
        if definitions:
            yield from definitions
        else:
            for occ in first_by_symbol.values():
                sl, sc, el, ec = occ.range
                yield SymbolDef(
                    symbol=occ.symbol,
                    path=doc.relative_path,
                    range=Range(sl, sc, el, ec),
                    language=doc.language,
                )


def get_top_level_definitions(definitions: list[SymbolDef]) -> list[SymbolDef]:
    """Filter to top-level definitions (not nested inside others).

    Parameters
    ----------
    definitions : list[SymbolDef]
        All symbol definitions for a file.

    Returns
    -------
    list[SymbolDef]
        Top-level definitions only.
    """

    # Check if def1 contains def2
    def contains(def1: SymbolDef, def2: SymbolDef) -> bool:
        """Check if def1's range contains def2's range (proper containment).

        Extended Summary
        ----------------
        Determines whether def1's source code range properly contains def2's range,
        meaning def2 is nested inside def1. This is used to filter out nested
        definitions (e.g., methods inside classes, inner functions) to identify
        only top-level definitions. Proper containment means def1's range encloses
        def2's range but they are not identical.

        Parameters
        ----------
        def1 : SymbolDef
            Outer symbol definition candidate. Its range is checked to see if it
            contains def2's range.
        def2 : SymbolDef
            Inner symbol definition candidate. Its range is checked to see if it
            is contained within def1's range.

        Returns
        -------
        bool
            True if def1's range properly contains def2's range (def2 is nested
            inside def1), False otherwise. Returns False if ranges are identical
            or def2 is not contained.

        Notes
        -----
        Time complexity O(1) - simple range comparison. Space complexity O(1).
        No I/O or side effects. Proper containment means:
        - def1.start_line <= def2.start_line
        - def1.end_line >= def2.end_line
        - Ranges are not identical (different start/end positions)
        This ensures nested definitions (methods, inner functions) are filtered
        out, leaving only top-level definitions.
        """
        r1, r2 = def1.range, def2.range
        return (
            r1.start_line <= r2.start_line
            and r1.end_line >= r2.end_line
            and not (
                r1.start_line == r2.start_line
                and r1.start_character == r2.start_character
                and r1.end_line == r2.end_line
                and r1.end_character == r2.end_character
            )
        )

    top_level = []
    for i, def1 in enumerate(definitions):
        is_nested = any(contains(def2, def1) for j, def2 in enumerate(definitions) if i != j)
        if not is_nested:
            top_level.append(def1)

    return sorted(top_level, key=lambda d: (d.range.start_line, d.range.start_character))


__all__ = [
    "Document",
    "Occurrence",
    "Range",
    "SCIPIndex",
    "SymbolDef",
    "extract_definitions",
    "get_top_level_definitions",
    "parse_scip_json",
]
