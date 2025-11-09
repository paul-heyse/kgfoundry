"""cAST chunking using SCIP symbol ranges.

Implements structure-aware chunking using symbol boundaries from SCIP
rather than tree-sitter parsing. Greedily packs top-level symbols up to
the character budget, splitting large symbols on blank lines.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True)
class LineIndex:
    """Line start bookkeeping for both character and byte positions."""

    char_starts: list[int]
    byte_starts: list[int]
    char_to_byte: list[int]

    @property
    def text_length(self) -> int:
        """Return the decoded text length in characters."""
        return len(self.char_to_byte) - 1


_ONE_BYTE_MAX = 0x7F
_TWO_BYTE_MAX = 0x7FF
_THREE_BYTE_MAX = 0xFFFF


def _utf8_length(ch: str) -> int:
    """Return the UTF-8 encoded length for ``ch``.

    Parameters
    ----------
    ch : str
        Single character to measure.

    Returns
    -------
    int
        Number of bytes required to encode the character in UTF-8 (1-4).
    """
    code_point = ord(ch)
    if code_point <= _ONE_BYTE_MAX:
        return 1
    if code_point <= _TWO_BYTE_MAX:
        return 2
    if code_point <= _THREE_BYTE_MAX:
        return 3
    return 4


def line_starts(text: str) -> LineIndex:
    """Compute character and byte offsets for each line start.

    Parameters
    ----------
    text : str
        Input text to index.

    Returns
    -------
    LineIndex
        Index containing character starts, byte starts, and character-to-byte mapping.
    """
    char_starts = [0]
    byte_starts = [0]
    char_to_byte = [0]
    byte_offset = 0

    for index, ch in enumerate(text):
        byte_offset += _utf8_length(ch)
        char_to_byte.append(byte_offset)
        if ch == "\n":
            char_starts.append(index + 1)
            byte_starts.append(byte_offset)

    return LineIndex(
        char_starts=char_starts, byte_starts=byte_starts, char_to_byte=char_to_byte
    )


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


def _char_index_for_line(line_index: LineIndex, line: int, character: int) -> int:
    """Map a line/character pair to an absolute character index.

    Parameters
    ----------
    line_index : LineIndex
        Line index containing character start positions.
    line : int
        Zero-based line number.
    character : int
        Zero-based character offset within the line.

    Returns
    -------
    int
        Absolute character index in the text, clamped to valid range.
    """
    if line >= len(line_index.char_starts):
        return line_index.text_length

    base = line_index.char_starts[line]
    candidate = base + character
    if candidate > line_index.text_length:
        return line_index.text_length
    return candidate


def range_to_bytes(text: str, line_index: LineIndex, rng: Range) -> tuple[int, int]:
    """Convert line/character range to byte offsets.

    Parameters
    ----------
    text : str
        Source text (unused, retained for backward compatibility).
    line_index : LineIndex
        Line index for character-to-byte conversion.
    rng : Range
        Range with start and end line/character positions.

    Returns
    -------
    tuple[int, int]
        Tuple of (start_byte, end_byte) offsets.
    """
    del text  # Parameters retained for backward compatibility.

    start_char = _char_index_for_line(line_index, rng.start_line, rng.start_character)
    end_char = _char_index_for_line(line_index, rng.end_line, rng.end_character)

    start_byte = line_index.char_to_byte[start_char]
    end_byte = line_index.char_to_byte[end_char]
    return start_byte, end_byte


@dataclass(slots=True)
class _ChunkAccumulator:
    """Accumulate SCIP symbol ranges into budgeted chunks."""

    uri: str
    text: str
    encoded: bytes
    line_index: LineIndex
    budget: int
    chunks: list[Chunk] = field(default_factory=list)
    _current_start_char: int | None = None
    _current_end_char: int | None = None
    _current_symbols: list[str] = field(default_factory=list)
    language: str = ""

    def add_symbol(self, symbol: SymbolDef, start: int, end: int) -> None:
        """Incorporate a symbol range into the current chunk set."""
        if self._current_start_char is None or self._current_end_char is None:
            self._start_chunk(start, end, symbol.symbol)
            return

        merged_end = max(self._current_end_char, end)
        if merged_end - self._current_start_char <= self.budget:
            self._current_end_char = merged_end
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
        self._current_start_char = start
        self._current_end_char = end
        self._current_symbols = [symbol]

    def _flush_current(self) -> None:
        if self._current_start_char is None or self._current_end_char is None:
            return
        self._append_chunk(
            self._current_start_char,
            self._current_end_char,
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
        start_byte = self.line_index.char_to_byte[start]
        end_byte = self.line_index.char_to_byte[end]
        if end_byte <= start_byte:
            return
        start_line = _line_index_from_byte(self.line_index.byte_starts, start_byte)
        end_line = _line_index_from_byte(
            self.line_index.byte_starts, max(end_byte - 1, 0)
        )
        chunk_text = self.encoded[start_byte:end_byte].decode("utf-8")
        self.chunks.append(
            Chunk(
                uri=self.uri,
                start_byte=start_byte,
                end_byte=end_byte,
                start_line=start_line,
                end_line=end_line,
                text=chunk_text,
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
        self._current_start_char = None
        self._current_end_char = None
        self._current_symbols = []


def chunk_file(
    path: Path,
    text: str,
    definitions: list[SymbolDef],
    *,
    options: ChunkOptions | None = None,
    budget: int | None = None,
) -> list[Chunk]:
    """Chunk file using SCIP symbol boundaries.

    Greedily packs top-level symbols up to a budget while optionally adding
    related-symbol overlap snippets for better context.

    Parameters
    ----------
    path : Path
        File path for the source code being chunked.
    text : str
        Complete file content as a string.
    definitions : list[SymbolDef]
        List of SCIP symbol definitions extracted from the file.
    options : ChunkOptions | None, optional
        Chunk generation configuration. If None, uses default options.
    budget : int | None, optional
        Override for the character budget applied during chunk assembly.

    Returns
    -------
    list[Chunk]
        List of generated chunks in source order.
    """
    if not definitions:
        return []

    opts = options or ChunkOptions()
    if budget is not None and budget != opts.budget:
        opts = replace(opts, budget=budget)
    chunk_language = (
        opts.language if opts.language is not None else definitions[0].language
    )

    uri = str(path)
    line_index = line_starts(text)
    encoded = text.encode("utf-8")
    accumulator = _ChunkAccumulator(
        uri=uri,
        text=text,
        encoded=encoded,
        line_index=line_index,
        budget=opts.budget,
        language=chunk_language,
    )

    symbols_with_positions = sorted(
        (
            (
                sym_def,
                _char_index_for_line(
                    line_index, sym_def.range.start_line, sym_def.range.start_character
                ),
                _char_index_for_line(
                    line_index, sym_def.range.end_line, sym_def.range.end_character
                ),
            )
            for sym_def in definitions
        ),
        key=lambda item: item[1],
    )

    for sym_def, start, end in symbols_with_positions:
        accumulator.add_symbol(sym_def, start, end)

    chunks = accumulator.finalize()

    if opts.overlap is not None:
        chunks = _apply_call_site_overlap(
            chunks=chunks,
            encoded=encoded,
            byte_starts=line_index.byte_starts,
            options=opts.overlap,
        )

    return chunks


@dataclass(frozen=True)
class ChunkOverlapOptions:
    """Configuration for adding call-site overlap snippets."""

    file_occurrences: list[tuple[str, int, int, int, int]]
    def_chunk_lookup: dict[str, int]
    max_related: int = 8
    overlap_lines: int = 8


@dataclass(frozen=True)
class ChunkOptions:
    """Chunk generation configuration."""

    budget: int = 2200
    language: str | None = None
    overlap: ChunkOverlapOptions | None = None


def _apply_call_site_overlap(
    *,
    chunks: list[Chunk],
    encoded: bytes,
    byte_starts: list[int],
    options: ChunkOverlapOptions,
) -> list[Chunk]:
    """Add call-site overlap snippets to chunks.

    Parameters
    ----------
    chunks : list[Chunk]
        Initial chunks to enhance with overlap snippets.
    encoded : bytes
        UTF-8 encoded file content.
    byte_starts : list[int]
        Byte offsets for each line start.
    options : ChunkOverlapOptions
        Overlap configuration including file occurrences and chunk lookup.

    Returns
    -------
    list[Chunk]
        Modified chunks with call-site overlap snippets added.
    """

    def _slice_lines(beg_line: int, end_line: int) -> str:
        bounded_start = min(max(beg_line, 0), len(byte_starts) - 1)
        bounded_end = min(max(end_line, 0), len(byte_starts) - 1)
        start_byte = byte_starts[bounded_start]
        end_byte = byte_starts[bounded_end]
        return encoded[start_byte:end_byte].decode("utf-8", errors="ignore")

    mutable = list(chunks)
    for idx, chunk in enumerate(mutable):
        begin, end = chunk.start_line, chunk.end_line
        seen: set[str] = set()
        for sym, sl, _sc, _el, _ec in options.file_occurrences:
            if (
                sl < begin
                or sl > end
                or sym not in options.def_chunk_lookup
                or sym in seen
            ):
                continue
            seen.add(sym)
            callee_chunk_id = options.def_chunk_lookup[sym]
            if callee_chunk_id == idx:
                continue
            callee = chunks[callee_chunk_id]
            footer = (
                "\n\n# related: "
                + sym
                + "\n"
                + _slice_lines(
                    max(callee.start_line - options.overlap_lines, 0),
                    min(callee.end_line + options.overlap_lines, callee.end_line + 1),
                )
            )
            mutable[idx] = Chunk(
                uri=chunk.uri,
                start_byte=chunk.start_byte,
                end_byte=chunk.end_byte,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text + "\n" + footer,
                symbols=tuple(sorted(set(chunk.symbols) | {sym})),
                language=chunk.language,
            )
            if len(seen) >= options.max_related:
                break

    return mutable


__all__ = [
    "Chunk",
    "chunk_file",
    "line_starts",
    "range_to_bytes",
]
