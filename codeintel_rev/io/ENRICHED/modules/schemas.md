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
- class: `SearchFilterPayload` (line 265)
- class: `SearchToolArgs` (line 287)
- class: `SearchExplainability` (line 296)
- class: `SearchResultMetadata` (line 305)
- class: `SearchResultItem` (line 318)
- class: `SearchStructuredContent` (line 330)
- class: `FetchToolArgs` (line 339)
- class: `FetchObjectMetadata` (line 346)
- class: `FetchObject` (line 357)
- class: `FetchStructuredContent` (line 367)
- class: `AnswerEnvelope` (line 373)
- class: `SymbolInfo` (line 465)
- class: `GitBlameEntry` (line 496)
- class: `OpenFileResponse` (line 529)
- class: `ListPathsResponse` (line 553)
- class: `BlameRangeResponse` (line 574)
- class: `FileHistoryResponse` (line 589)
- class: `SearchTextResponse` (line 604)

## Graph Metrics

- **fan_in**: 12
- **fan_out**: 1
- **cycle_group**: 37

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

AnswerEnvelope, BaseErrorFields, BlameRangeResponse, FetchObject, FetchObjectMetadata, FetchStructuredContent, FetchToolArgs, FileHistoryResponse, Finding, GitBlameEntry, ListPathsResponse, Location, Match, MethodInfo, OpenFileResponse, ScopeIn, SearchExplainability, SearchFilterPayload, SearchResultItem, SearchResultMetadata, SearchStructuredContent, SearchTextResponse, SearchToolArgs, SymbolInfo

## Doc Health

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

## Hotspot

- score: 1.81

## Side Effects

- network

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 651

## Doc Coverage

- `BaseErrorFields` (class): summary=yes, examples=no — Base fields present in ALL error responses.
- `ScopeIn` (class): summary=yes, examples=no — Query scope parameters for filtering search results.
- `Match` (class): summary=yes, examples=no — Search match result from text or semantic search.
- `Location` (class): summary=yes, examples=no — Source code location with precise line and column positions.
- `Finding` (class): summary=yes, examples=no — Generic finding result from code intelligence queries.
- `MethodInfo` (class): summary=yes, examples=no — Retrieval method metadata for search operations.
- `StageInfo` (class): summary=yes, examples=no — Timing metadata for an individual retrieval stage.
- `SearchFilterPayload` (class): summary=yes, examples=no — Structured filter payload for Deep Research search requests.
- `SearchToolArgs` (class): summary=yes, examples=no — Input schema for the MCP ``search`` tool.
- `SearchExplainability` (class): summary=yes, examples=no — Explainability payload attached to each search result.

## Tags

low-coverage, public-api, reexport-hub
