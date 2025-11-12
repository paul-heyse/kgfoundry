"""cAST chunking using SCIP symbol ranges.

Implements structure-aware chunking using symbol boundaries from SCIP
rather than tree-sitter parsing. Greedily packs top-level symbols up to
the character budget, splitting large symbols on blank lines.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
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

    return LineIndex(char_starts=char_starts, byte_starts=byte_starts, char_to_byte=char_to_byte)


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


@dataclass(slots=True, frozen=True)
class _ChunkAccumulator:
    """Immutable accumulator configuration; delegates mutation to a builder."""

    uri: str
    text: str
    encoded: bytes
    line_index: LineIndex
    budget: int
    language: str

    def build_chunks(
        self,
        symbols_with_positions: Sequence[tuple[SymbolDef, int, int]],
    ) -> list[Chunk]:
        """Build chunks from sorted symbol definitions using greedy packing.

        This method orchestrates the chunking process by creating a mutable
        builder instance and iteratively adding symbols to it. The builder
        greedily packs symbols up to the configured character budget, splitting
        large symbols on blank lines when necessary. After all symbols are
        processed, the builder finalizes and returns the complete list of chunks.

        Parameters
        ----------
        symbols_with_positions : Sequence[tuple[SymbolDef, int, int]]
            Sequence of (symbol definition, start character offset, end character
            offset) tuples. Symbols should be pre-sorted by start position to
            ensure correct chunk ordering. Character offsets are absolute positions
            within the source file text.

        Returns
        -------
        list[Chunk]
            List of chunks generated from the symbol definitions. Chunks are
            ordered by their position in the source file and respect symbol
            boundaries. Each chunk includes precise byte offsets, line numbers,
            text content, and associated symbol identifiers.

        Notes
        -----
        This method delegates the actual chunking logic to `_ChunkBuilder`, which
        handles greedy packing, budget management, and large symbol splitting.
        Time complexity: O(n) where n is the number of symbols, assuming symbol
        addition is O(1) amortized. The method performs no I/O operations and
        is thread-safe if called with distinct accumulator instances.
        """
        builder = _ChunkBuilder(config=self)
        for symbol, start, end in symbols_with_positions:
            builder.add_symbol(symbol, start, end)
        return builder.finalize()


class _ChunkBuilder:
    """Mutable helper that performs chunk assembly for a fixed configuration."""

    __slots__ = (
        "_chunks",
        "_config",
        "_current_end_char",
        "_current_start_char",
        "_current_symbols",
    )

    def __init__(self, config: _ChunkAccumulator) -> None:
        self._config = config
        self._chunks: list[Chunk] = []
        self._current_start_char: int | None = None
        self._current_end_char: int | None = None
        self._current_symbols: list[str] = []

    def add_symbol(self, symbol: SymbolDef, start: int, end: int) -> None:
        """Add a symbol to the current chunk or start a new chunk if needed.

        This method implements greedy chunk packing by attempting to merge the
        new symbol into the current chunk if it fits within the character budget.
        If merging would exceed the budget, the current chunk is finalized and
        a new chunk is started. Large symbols that exceed the budget alone are
        split across multiple chunks on blank line boundaries.

        Parameters
        ----------
        symbol : SymbolDef
            SCIP symbol definition to add. The symbol's range (start, end) is
            used to determine chunk boundaries and the symbol identifier is stored
            in the chunk's symbols tuple.
        start : int
            Starting character offset (0-indexed) of the symbol within the
            source file. Used to compute chunk boundaries and byte offsets.
        end : int
            Ending character offset (exclusive, 0-indexed) of the symbol. Used
            to compute chunk boundaries and determine if the symbol fits in the
            current chunk.

        Notes
        -----
        The method mutates the builder's internal state (_current_start_char,
        _current_end_char, _current_symbols) and may trigger chunk finalization
        (_flush_current) or large symbol splitting (_split_large_symbol). Time
        complexity: O(1) for normal symbol addition, O(n) for large symbol
        splitting where n is the number of blank-line-separated segments. The
        method performs no I/O operations and is not thread-safe (designed for
        single-threaded use within a single builder instance).
        """
        if self._current_start_char is None or self._current_end_char is None:
            self._start_chunk(start, end, symbol.symbol)
            return

        merged_end = max(self._current_end_char, end)
        if merged_end - self._current_start_char <= self._config.budget:
            self._current_end_char = merged_end
            self._current_symbols.append(symbol.symbol)
            return

        self._flush_current()
        if end - start > self._config.budget:
            self._split_large_symbol(symbol, start, end)
            self._reset()
            return

        self._start_chunk(start, end, symbol.symbol)

    def finalize(self) -> list[Chunk]:
        """Finalize chunk building and return the complete list of chunks.

        This method completes the chunking process by flushing any remaining
        in-progress chunk (if one exists) and returning the accumulated list
        of chunks. After finalization, the builder's internal state is cleared
        and the chunks list is ready for use in indexing or search operations.

        Returns
        -------
        list[Chunk]
            Complete list of chunks generated during the building process. Chunks
            are ordered by their position in the source file and include all
            symbols that were added via add_symbol(). The list may be empty if
            no symbols were added, but typically contains at least one chunk per
            file with symbol definitions.

        Notes
        -----
        This method should be called exactly once after all symbols have been
        added. Calling finalize() multiple times will flush the current chunk
        multiple times, potentially creating duplicate chunks. Time complexity:
        O(1) amortized if the current chunk is already finalized, O(k) where k
        is the number of symbols in the current chunk if flushing is needed.
        The method performs no I/O operations and is not thread-safe.
        """
        self._flush_current()
        return self._chunks

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
        start_byte = self._config.line_index.char_to_byte[start]
        end_byte = self._config.line_index.char_to_byte[end]
        if end_byte <= start_byte:
            return
        start_line = _line_index_from_byte(self._config.line_index.byte_starts, start_byte)
        end_line = _line_index_from_byte(self._config.line_index.byte_starts, max(end_byte - 1, 0))
        chunk_text = self._config.encoded[start_byte:end_byte].decode("utf-8")
        self._chunks.append(
            Chunk(
                uri=self._config.uri,
                start_byte=start_byte,
                end_byte=end_byte,
                start_line=start_line,
                end_line=end_line,
                text=chunk_text,
                symbols=symbols,
                language=self._config.language,
            )
        )

    def _split_large_symbol(self, symbol: SymbolDef, start: int, end: int) -> None:
        budget = self._config.budget
        text = self._config.text
        position = start
        while position < end:
            tentative_end = min(position + budget, end)
            search_start = position + budget // 2
            search_end = min(tentative_end, end)
            newline_idx = text.rfind("\n\n", search_start, search_end)
            if newline_idx != -1 and newline_idx > position:
                tentative_end = newline_idx + 1
            if tentative_end <= position:
                tentative_end = min(position + budget, end)
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
    chunk_language = opts.language if opts.language is not None else definitions[0].language

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

    chunks = accumulator.build_chunks(symbols_with_positions)

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
            if sl < begin or sl > end or sym not in options.def_chunk_lookup or sym in seen:
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
