# indexing/cast_chunker.py

## Docstring

```
cAST chunking using SCIP symbol ranges.

Implements structure-aware chunking using symbol boundaries from SCIP
rather than tree-sitter parsing. Greedily packs top-level symbols up to
the character budget, splitting large symbols on blank lines.
```

## Imports

- from **__future__** import annotations
- from **bisect** import bisect_right
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, replace
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **codeintel_rev.indexing.scip_reader** import Range, SymbolDef

## Definitions

- class: `Chunk` (line 21)
- class: `LineIndex` (line 81)
- function: `_utf8_length` (line 99)
- function: `line_starts` (line 122)
- function: `_line_index_from_byte` (line 150)
- function: `_char_index_for_line` (line 171)
- function: `range_to_bytes` (line 198)
- class: `_ChunkAccumulator` (line 226)
- class: `_ChunkBuilder` (line 278)
- function: `chunk_file` (line 447)
- class: `ChunkOverlapOptions` (line 528)
- class: `ChunkOptions` (line 538)
- function: `_apply_call_site_overlap` (line 546)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 57

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 13
- recent churn 90: 13

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Chunk, chunk_file, line_starts, range_to_bytes

## Doc Health

- **summary**: cAST chunking using SCIP symbol ranges.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.36

## Side Effects

- filesystem

## Complexity

- branches: 37
- cyclomatic: 38
- loc: 622

## Doc Coverage

- `Chunk` (class): summary=yes, examples=no — Code chunk with precise byte and line bounds.
- `LineIndex` (class): summary=yes, examples=no — Line start bookkeeping for both character and byte positions.
- `_utf8_length` (function): summary=yes, params=ok, examples=no — Return the UTF-8 encoded length for ``ch``.
- `line_starts` (function): summary=yes, params=ok, examples=no — Compute character and byte offsets for each line start.
- `_line_index_from_byte` (function): summary=yes, params=ok, examples=no — Return the zero-based line index containing ``byte_offset``.
- `_char_index_for_line` (function): summary=yes, params=ok, examples=no — Map a line/character pair to an absolute character index.
- `range_to_bytes` (function): summary=yes, params=ok, examples=no — Convert line/character range to byte offsets.
- `_ChunkAccumulator` (class): summary=yes, examples=no — Immutable accumulator configuration; delegates mutation to a builder.
- `_ChunkBuilder` (class): summary=yes, examples=no — Mutable helper that performs chunk assembly for a fixed configuration.
- `chunk_file` (function): summary=yes, params=ok, examples=no — Chunk file using SCIP symbol boundaries.

## Tags

low-coverage, public-api
