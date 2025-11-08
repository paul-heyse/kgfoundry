"""cAST chunking using SCIP symbol ranges.

Implements structure-aware chunking using symbol boundaries from SCIP
rather than tree-sitter parsing. Greedily packs top-level symbols up to
the character budget, splitting large symbols on blank lines.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codeintel_rev.indexing.scip_reader import Range, SymbolDef


@dataclass(frozen=True)
class Chunk:
    """Code chunk with precise byte and line bounds.

    A Chunk represents a contiguous region of source code that has been extracted
    for indexing. Chunks are created by the cAST chunker using SCIP symbol boundaries
    to ensure that chunks respect semantic structure (functions, classes, etc.) rather
    than arbitrary text splits.

    Each chunk includes precise byte offsets (for exact text extraction) and line
    numbers (for human-readable display). The chunk also tracks which SCIP symbols
    it contains, enabling symbol-aware search and navigation.

    Chunks are immutable (frozen dataclass) to ensure thread safety and prevent
    accidental modification. They are designed to be stored in Parquet files with
    their embeddings for efficient retrieval.

    Attributes
    ----------
    uri : str
        File path or URI identifying the source file. This is typically a relative
        path from the repository root, matching the SCIP index format. Used for
        filtering and grouping chunks by file.
    start_byte : int
        Starting byte offset (0-indexed) of the chunk within the source file.
        Used for precise text extraction without re-parsing the file. Byte offsets
        are more reliable than character offsets for multi-byte encodings.
    end_byte : int
        Ending byte offset (exclusive, 0-indexed) of the chunk. The chunk text
        spans from start_byte to end_byte (exclusive).
    start_line : int
        Starting line number (0-indexed) for human-readable display. Used in search
        results and code navigation. Line numbers are computed from byte offsets
        using line start positions.
    end_line : int
        Ending line number (0-indexed, inclusive). The chunk spans from start_line
        to end_line (inclusive). Used for displaying code ranges in search results.
    text : str
        The actual source code text of the chunk. This is the substring of the
        source file from start_byte to end_byte. Stored explicitly for fast
        retrieval without re-reading files.
    symbols : tuple[str, ...]
        Tuple of SCIP symbol strings that are defined or referenced within this
        chunk. Symbols are in SCIP format (e.g., "python kgfoundry.core#Function.main").
        Used for symbol-aware search and filtering. Empty tuple if no symbols.
    language : str
        Programming language of the source file containing this chunk. Used for
        filtering results by language scope and derived from SCIP metadata.
    """

    uri: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    text: str
    symbols: tuple[str, ...]
    language: str


def line_starts(text: str) -> list[int]:
    """Compute byte offsets of each line start.

    Parameters
    ----------
    text : str
        Source file content.

    Returns
    -------
    list[int]
        Byte offsets for start of each line.
    """
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_index_from_byte(starts: Sequence[int], byte_offset: int) -> int:
    """Return the zero-based line index containing ``byte_offset``.

    Parameters
    ----------
    starts : Sequence[int]
        Offsets for the beginning of each line.
    byte_offset : int
        Absolute byte offset within the text.

    Returns
    -------
    int
        Zero-based line index best matching the offset.
    """
    index = bisect_right(starts, byte_offset) - 1
    if index < 0:
        return 0
    return min(index, len(starts) - 1)


def range_to_bytes(text: str, starts: list[int], rng: Range) -> tuple[int, int]:
    """Convert line/char range to byte offsets.

    Parameters
    ----------
    text : str
        Source file content.
    starts : list[int]
        Line start offsets from line_starts().
    rng : Range
        SCIP range (0-indexed lines and characters).

    Returns
    -------
    tuple[int, int]
        (start_byte, end_byte).
    """
    n = len(text)

    # Start position
    if rng.start_line < len(starts):
        start = min(starts[rng.start_line] + rng.start_character, n)
    else:
        start = n

    end_candidate = starts[rng.end_line] + rng.end_character if rng.end_line < len(starts) else n
    end = min(end_candidate, n)

    return start, end


@dataclass(slots=True)
class _ChunkAccumulator:
    """Accumulate SCIP symbol ranges into budgeted chunks."""

    uri: str
    text: str
    starts: Sequence[int]
    budget: int
    chunks: list[Chunk] = field(default_factory=list)
    _current_start: int | None = None
    _current_end: int | None = None
    _current_symbols: list[str] = field(default_factory=list)
    language: str = ""

    def add_symbol(self, symbol: SymbolDef, start: int, end: int) -> None:
        """Incorporate a symbol range into the current chunk set."""
        if self._current_start is None or self._current_end is None:
            self._start_chunk(start, end, symbol.symbol)
            return

        merged_end = max(self._current_end, end)
        if merged_end - self._current_start <= self.budget:
            self._current_end = merged_end
            self._current_symbols.append(symbol.symbol)
            return

        self._flush_current()
        if end - start > self.budget:
            self._split_large_symbol(symbol, start, end)
            self._reset()
            return

        self._start_chunk(start, end, symbol.symbol)

    def finalize(self) -> list[Chunk]:
        """Flush any pending chunk and return accumulated results.

        Returns
        -------
        list[Chunk]
            All generated chunks in source order.
        """
        self._flush_current()
        return self.chunks

    def _start_chunk(self, start: int, end: int, symbol: str) -> None:
        self._current_start = start
        self._current_end = end
        self._current_symbols = [symbol]

    def _flush_current(self) -> None:
        if self._current_start is None or self._current_end is None:
            return
        self._append_chunk(
            self._current_start,
            self._current_end,
            tuple(self._current_symbols),
        )
        self._reset()

    def _append_chunk(
        self,
        start: int,
        end: int,
        symbols: tuple[str, ...],
    ) -> None:
        if end <= start:
            return
        start_line = _line_index_from_byte(self.starts, start)
        end_line = _line_index_from_byte(self.starts, max(end - 1, 0))
        self.chunks.append(
            Chunk(
                uri=self.uri,
                start_byte=start,
                end_byte=end,
                start_line=start_line,
                end_line=end_line,
                text=self.text[start:end],
                symbols=symbols,
                language=self.language,
            )
        )

    def _split_large_symbol(
        self,
        symbol: SymbolDef,
        start: int,
        end: int,
    ) -> None:
        """Split an oversized symbol range on blank-line boundaries."""
        position = start
        while position < end:
            tentative_end = min(position + self.budget, end)
            search_start = position + self.budget // 2
            search_end = min(tentative_end, end)
            newline_idx = self.text.rfind("\n\n", search_start, search_end)
            if newline_idx != -1 and newline_idx > position:
                tentative_end = newline_idx + 1
            if tentative_end <= position:
                tentative_end = min(position + self.budget, end)
                if tentative_end <= position:
                    tentative_end = end
            self._append_chunk(
                position,
                tentative_end,
                (symbol.symbol,),
            )
            position = tentative_end

    def _reset(self) -> None:
        self._current_start = None
        self._current_end = None
        self._current_symbols = []


def chunk_file(
    path: Path,
    text: str,
    definitions: list[SymbolDef],
    budget: int = 2200,
    language: str | None = None,
) -> list[Chunk]:
    """Chunk file using SCIP symbol boundaries.

    Greedily packs top-level symbols up to budget; splits large symbols on
    blank lines.

    Parameters
    ----------
    path : Path
        File path.
    text : str
        File content.
    definitions : list[SymbolDef]
        Symbol definitions for this file (should be top-level only).
    budget : int
        Target chunk size in characters.

    Returns
    -------
        list[Chunk]
            Generated chunks.
    """
    if not definitions:
        return []

    chunk_language = language if language is not None else definitions[0].language

    uri = str(path)
    starts = line_starts(text)
    accumulator = _ChunkAccumulator(
        uri=uri,
        text=text,
        starts=starts,
        budget=budget,
        language=chunk_language,
    )

    symbols_with_bytes = sorted(
        ((sym_def, *range_to_bytes(text, starts, sym_def.range)) for sym_def in definitions),
        key=lambda item: item[1],
    )

    for sym_def, start, end in symbols_with_bytes:
        accumulator.add_symbol(sym_def, start, end)

    return accumulator.finalize()


__all__ = [
    "Chunk",
    "chunk_file",
    "line_starts",
    "range_to_bytes",
]
