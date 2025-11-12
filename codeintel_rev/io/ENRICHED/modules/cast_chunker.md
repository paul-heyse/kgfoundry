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

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 2
- **cycle_group**: 56

## Declared Exports (__all__)

Chunk, chunk_file, line_starts, range_to_bytes

## Tags

public-api
