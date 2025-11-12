# mcp_server/schemas.py

## Docstring

```
MCP server schemas using TypedDict for FastMCP compatibility.

TypedDict provides automatic JSON Schema generation for FastMCP tools.
```

## Imports

- from **__future__** import annotations
- from **typing** import Literal, NotRequired, TypedDict
- from **kgfoundry_common.problem_details** import ProblemDetailsDict

## Definitions

- class: `BaseErrorFields` (line 13)
- class: `ScopeIn` (line 35)
- class: `Match` (line 92)
- class: `Location` (line 130)
- class: `Finding` (line 168)
- class: `MethodInfo` (line 218)
- class: `StageInfo` (line 256)
- class: `AnswerEnvelope` (line 265)
- class: `SymbolInfo` (line 352)
- class: `GitBlameEntry` (line 383)
- class: `OpenFileResponse` (line 416)
- class: `ListPathsResponse` (line 440)
- class: `BlameRangeResponse` (line 461)
- class: `FileHistoryResponse` (line 476)
- class: `SearchTextResponse` (line 491)

## Dependency Graph

- **fan_in**: 11
- **fan_out**: 1
- **cycle_group**: 25

## Declared Exports (__all__)

AnswerEnvelope, BaseErrorFields, BlameRangeResponse, FileHistoryResponse, Finding, GitBlameEntry, ListPathsResponse, Location, Match, MethodInfo, OpenFileResponse, ScopeIn, SearchTextResponse, SymbolInfo

## Doc Metrics

- **summary**: MCP server schemas using TypedDict for FastMCP compatibility.
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

## Hotspot Score

- score: 1.78

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 528

## Doc Coverage

- `BaseErrorFields` (class): summary=yes, examples=no — Base fields present in ALL error responses.
- `ScopeIn` (class): summary=yes, examples=no — Query scope parameters for filtering search results.
- `Match` (class): summary=yes, examples=no — Search match result from text or semantic search.
- `Location` (class): summary=yes, examples=no — Source code location with precise line and column positions.
- `Finding` (class): summary=yes, examples=no — Generic finding result from code intelligence queries.
- `MethodInfo` (class): summary=yes, examples=no — Retrieval method metadata for search operations.
- `StageInfo` (class): summary=yes, examples=no — Timing metadata for an individual retrieval stage.
- `AnswerEnvelope` (class): summary=yes, examples=no — Standard response envelope for MCP code intelligence tools.
- `SymbolInfo` (class): summary=yes, examples=no — Symbol information with location and documentation.
- `GitBlameEntry` (class): summary=yes, examples=no — Git blame entry for a single line of code.

## Tags

low-coverage, public-api, reexport-hub
